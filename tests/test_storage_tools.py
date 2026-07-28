import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.storage import RentalStore
from src.tools import AVAILABLE_TOOLS, RentalTools, create_tool_registry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = PROJECT_ROOT / "config" / "rental_inventory.json"
FIXED_NOW = datetime(2026, 7, 28, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))


def make_tools(_tmp_path):
    store = RentalStore(
        db_path=":memory:",
        inventory_path=INVENTORY_PATH,
        now_factory=lambda: FIXED_NOW,
    )
    store.initialize()
    return store, RentalTools(store)


def test_user_can_find_accent_insensitive_matching_properties(tmp_path):
    store, tools = make_tools(tmp_path)

    result = tools.search_properties(
        city="Ha Noi",
        district="Cau Giay",
        max_price_vnd=5_000_000,
        amenities=["điều hòa", "chỗ để xe"],
    )

    assert result["ok"] is True
    assert result["code"] == "OK"
    assert [item["property_id"] for item in result["data"]["properties"]] == [
        "HN-CG-001",
        "HN-CG-002",
    ]
    assert result["data"]["total"] == 2
    store.close()


def test_user_can_get_grounded_property_details(tmp_path):
    store, tools = make_tools(tmp_path)

    result = tools.get_property_details("HCM-BT-001")

    assert result["ok"] is True
    assert result["data"]["property"]["price_vnd"] == 9_500_000
    assert result["data"]["property"]["district"] == "Bình Thạnh"
    assert result["data"]["property"]["area_m2"] == 32
    store.close()


def test_user_can_compare_two_or_three_properties_deterministically(tmp_path):
    store, tools = make_tools(tmp_path)

    result = tools.compare_properties(
        ["HCM-BT-001", "HCM-BT-002", "HCM-PN-001"]
    )

    assert result["ok"] is True
    assert result["data"]["highlights"] == {
        "lowest_price_property_id": "HCM-BT-001",
        "largest_area_property_id": "HCM-BT-002",
        "lowest_deposit_property_id": "HCM-PN-001",
    }
    assert [item["property_id"] for item in result["data"]["properties"]] == [
        "HCM-BT-001",
        "HCM-BT-002",
        "HCM-PN-001",
    ]
    store.close()


def test_user_can_see_fourteen_upcoming_days_of_available_slots(tmp_path):
    store, tools = make_tools(tmp_path)

    result = tools.get_available_viewing_slots("HN-CG-001")

    assert result["ok"] is True
    assert result["data"]["total"] == 42
    assert result["data"]["slots"][0]["date"] == "2026-07-29"
    assert result["data"]["slots"][-1]["date"] == "2026-08-11"
    store.close()


def test_user_can_book_an_available_slot_with_a_vietnam_phone(tmp_path):
    store, tools = make_tools(tmp_path)

    result = tools.book_viewing(
        property_id="HN-CG-001",
        slot_id="HN-CG-001-20260729-1400",
        viewer_name="Nguyễn Văn An",
        viewer_phone="+84 912 345 678",
        session_id="session-001",
    )

    assert result["ok"] is True
    assert result["code"] == "OK"
    assert result["data"]["booking"]["property_id"] == "HN-CG-001"
    assert result["data"]["booking"]["viewer_phone"] == "0912***678"
    assert result["data"]["booking"]["status"] == "confirmed"
    store.close()


def test_booking_list_is_session_scoped_and_masks_phone(tmp_path):
    store, tools = make_tools(tmp_path)
    tools.book_viewing(
        "HN-CG-001",
        "HN-CG-001-20260729-1400",
        "Nguyễn Văn An",
        "0912345678",
        session_id="session-001",
    )
    tools.book_viewing(
        "HCM-BT-001",
        "HCM-BT-001-20260729-1400",
        "Trần Thị Bình",
        "0987654321",
        session_id="session-002",
    )

    bookings = store.list_bookings("session-001")

    assert len(bookings) == 1
    assert bookings[0]["property_id"] == "HN-CG-001"
    assert bookings[0]["viewer_phone"] == "0912***678"
    assert "0912345678" not in str(bookings)
    store.close()


def test_booking_export_is_json_ready_and_contains_no_raw_phone(tmp_path):
    store, tools = make_tools(tmp_path)
    tools.book_viewing(
        "HN-CG-001",
        "HN-CG-001-20260729-1830",
        "Nguyễn Văn An",
        "0912345678",
        session_id="session-001",
    )

    export = store.export_bookings("session-001")
    serialized = json.dumps(export, ensure_ascii=False)

    assert export["schema_version"] == "1.0"
    assert export["session_id"] == "session-001"
    assert export["total"] == 1
    assert export["bookings"][0]["viewer_phone"] == "0912***678"
    assert "0912345678" not in serialized
    store.close()


def test_duplicate_slot_booking_returns_conflict_and_preserves_first_booking(tmp_path):
    store, tools = make_tools(tmp_path)
    first = tools.book_viewing(
        "HN-CG-001",
        "HN-CG-001-20260729-0900",
        "Nguyễn Văn An",
        "0912345678",
        session_id="session-first",
    )

    second = tools.book_viewing(
        "HN-CG-001",
        "HN-CG-001-20260729-0900",
        "Trần Thị Bình",
        "0987654321",
        session_id="session-second",
    )

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["code"] == "CONFLICT"
    assert len(store.list_bookings("session-first")) == 1
    assert store.list_bookings("session-second") == []
    store.close()


def test_booking_without_trusted_session_is_blocked_without_side_effect(tmp_path):
    store, tools = make_tools(tmp_path)

    result = tools.book_viewing(
        "HN-CG-001",
        "HN-CG-001-20260729-0900",
        "Nguyễn Văn An",
        "0912345678",
    )

    assert result["ok"] is False
    assert result["code"] == "CONFIRMATION_REQUIRED"
    assert store.list_available_slots("HN-CG-001", "2026-07-29")[0]["slot_id"] == (
        "HN-CG-001-20260729-0900"
    )
    store.close()


def test_available_slots_support_date_and_vietnamese_period_filters(tmp_path):
    store, tools = make_tools(tmp_path)

    result = tools.get_available_viewing_slots(
        "HN-CG-001",
        date="2026-08-01",
        time_of_day="buổi chiều",
    )

    assert result["ok"] is True
    assert result["data"]["slots"] == [
        {
            "slot_id": "HN-CG-001-20260801-1400",
            "property_id": "HN-CG-001",
            "starts_at": "2026-08-01T14:00:00+07:00",
            "date": "2026-08-01",
            "time": "14:00",
            "time_of_day": "afternoon",
        }
    ]
    store.close()


def test_invalid_inputs_return_safe_error_envelopes(tmp_path):
    store, tools = make_tools(tmp_path)

    results = [
        tools.search_properties(city="", max_price_vnd=-1),
        tools.get_property_details("UNKNOWN"),
        tools.compare_properties(["HN-CG-001"]),
        tools.get_available_viewing_slots("HN-CG-001", date="32/13/2026"),
        tools.book_viewing(
            "HN-CG-001",
            "HN-CG-001-20260729-0900",
            "Nguyễn Văn An",
            "12345",
            session_id="session-001",
        ),
    ]

    assert [result["code"] for result in results] == [
        "INVALID_ARGUMENT",
        "NOT_FOUND",
        "INVALID_ARGUMENT",
        "INVALID_ARGUMENT",
        "INVALID_ARGUMENT",
    ]
    assert all(set(result) == {"ok", "code", "message", "data"} for result in results)
    store.close()


def test_registry_exposes_exactly_five_bound_tools_without_global_store(tmp_path):
    store, _ = make_tools(tmp_path)

    registry = create_tool_registry(store)

    expected_names = {
        "search_properties",
        "get_property_details",
        "compare_properties",
        "get_available_viewing_slots",
        "book_viewing",
    }
    assert set(registry) == expected_names
    assert set(AVAILABLE_TOOLS) == expected_names
    assert all(callable(tool) for tool in registry.values())
    store.close()
