from pathlib import Path

from fastapi.testclient import TestClient

from src.app import AgentEngine
from src.providers import MockProvider
from src.storage import RentalStore
from src.tools import create_tool_registry
from src.web_api import ConfirmationTokenRegistry, create_app


class ScriptedProvider:
    model_name = "scripted-test"

    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def generate(self, prompt, system_prompt=""):
        return next(self.outputs)


class FakeStore:
    def list_bookings(self, session_id):
        return [
            {
                "booking_id": "BK-001",
                "session_id": session_id,
                "property_id": "HN-CG-001",
                "viewer_phone": "091****678",
            }
        ]

    def export_bookings(self, session_id):
        return self.list_bookings(session_id)


def test_confirmation_registry_reserves_atomically_releases_and_expires():
    now = [100.0]
    registry = ConfirmationTokenRegistry(
        ttl_seconds=30,
        clock=lambda: now[0],
    )
    token = registry.issue("session-1", "HN-CG-001", "SLOT-01")

    assert (
        registry.acquire(
            token,
            session_id="another-session",
            property_id="HN-CG-001",
            slot_id="SLOT-01",
        )
        is False
    )
    assert registry.acquire(
        token,
        session_id="session-1",
        property_id="HN-CG-001",
        slot_id="SLOT-01",
    )
    assert (
        registry.acquire(
            token,
            session_id="session-1",
            property_id="HN-CG-001",
            slot_id="SLOT-01",
        )
        is False
    )

    registry.finalize(token, booking_created=False)
    assert registry.acquire(
        token,
        session_id="session-1",
        property_id="HN-CG-001",
        slot_id="SLOT-01",
    )
    registry.finalize(token, booking_created=False)

    now[0] += 31
    assert (
        registry.acquire(
            token,
            session_id="session-1",
            property_id="HN-CG-001",
            slot_id="SLOT-01",
        )
        is False
    )


def test_session_and_chat_endpoints_return_stable_contract():
    provider = ScriptedProvider(
        ["Tôi có thể hướng dẫn bạn kiểm tra hợp đồng thuê nhà."]
    )
    engine = AgentEngine(provider, {})
    client = TestClient(create_app(engine=engine, store=FakeStore()))

    session_response = client.post("/api/sessions")
    assert session_response.status_code == 201
    session_id = session_response.json()["session_id"]

    chat_response = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Cần kiểm tra gì trước khi thuê nhà?",
            "mode": "level2",
        },
    )

    assert chat_response.status_code == 200
    payload = chat_response.json()
    assert payload["session_id"] == session_id
    assert payload["mode_used"] == "level2"
    assert payload["tool_calls"] == []
    assert payload["requires_confirmation"] is False


def test_booking_export_is_json_attachment_with_masked_phone():
    engine = AgentEngine(ScriptedProvider([]), {})
    client = TestClient(create_app(engine=engine, store=FakeStore()))
    session_id = client.post("/api/sessions").json()["session_id"]

    response = client.get(
        "/api/bookings/export",
        params={"session_id": session_id},
    )

    assert response.status_code == 200
    assert "attachment;" in response.headers["content-disposition"]
    assert response.json()["bookings"][0]["viewer_phone"] == "091****678"


def test_health_reports_runtime_readiness():
    engine = AgentEngine(ScriptedProvider([]), {})
    client = TestClient(create_app(engine=engine, store=FakeStore()))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "provider": "ScriptedProvider",
        "database": "ok",
    }


def test_booking_requires_server_issued_token_and_consumes_it_after_success():
    provider = ScriptedProvider(
        [
            (
                "Thought: Cần tra lịch thật.\n"
                'Action: {"tool":"get_available_viewing_slots","args":'
                '{"property_id":"HN-CG-001"}}'
            ),
            (
                "Thought: Đã có lịch thật.\n"
                "Final Answer: Hãy chọn một khung giờ."
            ),
            (
                "Thought: Dùng xác nhận đáng tin cậy.\n"
                'Action: {"tool":"book_viewing","args":'
                '{"property_id":"HN-CG-001","slot_id":"SLOT-01",'
                '"viewer_name":"[provided securely]",'
                '"viewer_phone":"[provided securely]"}}'
            ),
            (
                "Thought: Booking đã được ghi nhận.\n"
                "Final Answer: Đặt lịch thành công."
            ),
        ]
    )
    booked = []

    def get_available_viewing_slots(property_id):
        return {
            "ok": True,
            "code": "OK",
            "message": "Còn một lịch.",
            "data": {
                "slots": [
                    {
                        "slot_id": "SLOT-01",
                        "property_id": property_id,
                        "starts_at": "2026-08-01T09:00:00+07:00",
                    }
                ]
            },
        }

    def book_viewing(**kwargs):
        booked.append(kwargs)
        return {
            "ok": True,
            "code": "OK",
            "message": "Đã đặt.",
            "data": {
                "booking": {
                    "booking_id": "BK-001",
                    "property_id": kwargs["property_id"],
                    "slot_id": kwargs["slot_id"],
                    "viewer_phone": kwargs["viewer_phone"],
                }
            },
        }

    engine = AgentEngine(
        provider,
        {
            "get_available_viewing_slots": get_available_viewing_slots,
            "book_viewing": book_viewing,
        },
    )
    client = TestClient(create_app(engine=engine, store=FakeStore()))
    session_id = client.post("/api/sessions").json()["session_id"]

    slots_response = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Kiểm tra lịch xem căn HN-CG-001.",
            "mode": "level3",
        },
    )
    assert slots_response.status_code == 200
    slot = slots_response.json()["slots"][0]
    token = slot["confirmation_token"]
    assert len(token) >= 32

    confirmation = {
        "accepted": True,
        "property_id": "HN-CG-001",
        "slot_id": "SLOT-01",
        "viewer_name": "Nguyễn An",
        "viewer_phone": "0912345678",
    }
    forged_response = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Xác nhận đặt lịch.",
            "mode": "level3",
            "confirmation": {**confirmation, "token": "x" * 43},
        },
    )
    assert forged_response.status_code == 403
    assert booked == []

    mismatched_response = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Xác nhận một slot khác.",
            "mode": "level3",
            "confirmation": {
                **confirmation,
                "slot_id": "SLOT-OTHER",
                "token": token,
            },
        },
    )
    assert mismatched_response.status_code == 403
    assert booked == []

    booking_response = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Xác nhận đặt lịch.",
            "mode": "level3",
            "confirmation": {**confirmation, "token": token},
        },
    )
    assert booking_response.status_code == 200
    assert booking_response.json()["booking"]["booking_id"] == "BK-001"
    assert booked[0]["viewer_name"] == "Nguyễn An"
    assert booked[0]["viewer_phone"] == "0912345678"

    reused_response = client.post(
        "/api/chat",
        json={
            "session_id": session_id,
            "message": "Xác nhận đặt lịch lần nữa.",
            "mode": "level3",
            "confirmation": {**confirmation, "token": token},
        },
    )
    assert reused_response.status_code == 403


def test_real_mock_http_flow_persists_and_exports_one_masked_booking(tmp_path):
    inventory_path = (
        Path(__file__).resolve().parents[1] / "config" / "rental_inventory.json"
    )
    store = RentalStore(
        tmp_path / "rentmate-http.db",
        inventory_path=inventory_path,
    )
    store.initialize()
    try:
        engine = AgentEngine(MockProvider(), create_tool_registry(store))
        client = TestClient(create_app(engine=engine, store=store))
        session_id = client.post("/api/sessions").json()["session_id"]

        search_response = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "message": (
                    "Tìm căn hộ ở Bình Thạnh, TP.HCM dưới 12 triệu, diện tích "
                    "từ 30 m². So sánh tối đa 3 căn rồi kiểm tra lịch xem còn "
                    "trống vào cuối tuần."
                ),
                "mode": "level3",
            },
        )
        assert search_response.status_code == 200
        selected_slot = search_response.json()["slots"][0]

        booking_response = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "message": "Tôi xác nhận đặt lịch theo khung giờ đã chọn.",
                "mode": "level3",
                "confirmation": {
                    "token": selected_slot["confirmation_token"],
                    "accepted": True,
                    "property_id": selected_slot["property_id"],
                    "slot_id": selected_slot["slot_id"],
                    "viewer_name": "Nguyễn An",
                    "viewer_phone": "0912345678",
                },
            },
        )

        assert booking_response.status_code == 200
        assert booking_response.json()["booking"]["viewer_phone"] == "0912***678"
        bookings = client.get(
            "/api/bookings",
            params={"session_id": session_id},
        ).json()["bookings"]
        assert len(bookings) == 1
        assert bookings[0]["viewer_phone"] == "0912***678"

        exported = client.get(
            "/api/bookings/export",
            params={"session_id": session_id},
        )
        assert exported.status_code == 200
        assert exported.json()["bookings"][0]["viewer_phone"] == "0912***678"
    finally:
        store.close()
