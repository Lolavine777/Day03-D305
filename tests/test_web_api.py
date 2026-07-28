from fastapi.testclient import TestClient

from src.app import AgentEngine
from src.web_api import create_app


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
