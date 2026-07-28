"""Validated RentMate tools exposed to the ReAct executor."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any, Callable, TypedDict

try:
    from .storage import RentalStore, RentalStoreError
except ImportError:  # Supports ``python src/app.py``.
    from storage import RentalStore, RentalStoreError


class ToolResult(TypedDict):
    """Stable JSON-serializable envelope returned by every rental tool."""

    ok: bool
    code: str
    message: str
    data: dict[str, Any]


def _result(
    ok: bool,
    code: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> ToolResult:
    return {
        "ok": ok,
        "code": code,
        "message": message,
        "data": data or {},
    }


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.strip().casefold())
    without_accents = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    ).replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", without_accents).strip()


def _normalize_vietnam_phone(value: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0084"):
        digits = f"0{digits[4:]}"
    elif digits.startswith("84"):
        digits = f"0{digits[2:]}"
    if not re.fullmatch(r"0[35789]\d{8}", digits):
        return None
    return digits


def _mask_phone(value: str) -> str:
    return f"{value[:4]}***{value[-3:]}"


_CITY_ALIASES = {
    "ha noi": "ha noi",
    "hanoi": "ha noi",
    "tp hcm": "tp hcm",
    "tphcm": "tp hcm",
    "hcm": "tp hcm",
    "ho chi minh": "tp hcm",
    "thanh pho ho chi minh": "tp hcm",
    "sai gon": "tp hcm",
    "saigon": "tp hcm",
}


class RentalTools:
    """Five public rental actions bound to one :class:`RentalStore`."""

    def __init__(self, store: RentalStore) -> None:
        self.store = store

    def search_properties(
        self,
        city: str,
        district: str | None = None,
        max_price_vnd: int | float | None = None,
        property_type: str | None = None,
        min_area_m2: int | float | None = None,
        amenities: list[str] | str | None = None,
        limit: int = 5,
    ) -> ToolResult:
        """Find available rentals using strict, accent-insensitive filters.

        Args:
            city: Required city name or common Hà Nội/TP.HCM alias.
            district: Optional district name.
            max_price_vnd: Optional inclusive monthly price ceiling in VND.
            property_type: Optional rental type such as ``phòng trọ``.
            min_area_m2: Optional inclusive minimum floor area.
            amenities: Amenities that must all be present.
            limit: Maximum number of ranked results, from 1 to 20.

        Returns:
            ``ToolResult`` containing matching properties sorted by monthly
            price, then larger area, then property id.

        Errors:
            ``INVALID_ARGUMENT`` for malformed filters and ``NO_RESULTS`` when
            the inventory has no matching available property.

        Side effects:
            None.
        """
        if not isinstance(city, str) or not city.strip():
            return _result(False, "INVALID_ARGUMENT", "Thành phố không được để trống.")
        if isinstance(max_price_vnd, bool) or (
            max_price_vnd is not None
            and (not isinstance(max_price_vnd, (int, float)) or max_price_vnd <= 0)
        ):
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Giá tối đa phải là một số dương.",
            )
        if isinstance(min_area_m2, bool) or (
            min_area_m2 is not None
            and (not isinstance(min_area_m2, (int, float)) or min_area_m2 <= 0)
        ):
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Diện tích tối thiểu phải là một số dương.",
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Giới hạn kết quả phải là số nguyên từ 1 đến 20.",
            )

        amenity_values: list[str]
        if amenities is None:
            amenity_values = []
        elif isinstance(amenities, str):
            amenity_values = [
                item.strip() for item in amenities.split(",") if item.strip()
            ]
        elif isinstance(amenities, list) and all(
            isinstance(item, str) and item.strip() for item in amenities
        ):
            amenity_values = amenities
        else:
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Tiện ích phải là chuỗi hoặc danh sách chuỗi không rỗng.",
            )

        normalized_city = _normalized_text(city)
        target_city = _CITY_ALIASES.get(normalized_city, normalized_city)
        normalized_district = (
            _normalized_text(district)
            if isinstance(district, str) and district.strip()
            else None
        )
        normalized_type = (
            _normalized_text(property_type)
            if isinstance(property_type, str) and property_type.strip()
            else None
        )
        required_amenities = {_normalized_text(item) for item in amenity_values}

        matches: list[dict[str, Any]] = []
        for property_item in self.store.list_properties():
            property_city = _CITY_ALIASES.get(
                _normalized_text(property_item["city"]),
                _normalized_text(property_item["city"]),
            )
            property_amenities = {
                _normalized_text(item) for item in property_item["amenities"]
            }
            if not property_item["available"] or property_city != target_city:
                continue
            if (
                normalized_district
                and _normalized_text(property_item["district"]) != normalized_district
            ):
                continue
            if (
                max_price_vnd is not None
                and property_item["price_vnd"] > max_price_vnd
            ):
                continue
            if (
                normalized_type
                and _normalized_text(property_item["property_type"]) != normalized_type
            ):
                continue
            if (
                min_area_m2 is not None
                and property_item["area_m2"] < min_area_m2
            ):
                continue
            if not required_amenities.issubset(property_amenities):
                continue
            matches.append(property_item)

        matches.sort(
            key=lambda item: (
                item["price_vnd"],
                -item["area_m2"],
                item["property_id"],
            )
        )
        selected = matches[:limit]
        if not selected:
            return _result(
                False,
                "NO_RESULTS",
                "Không tìm thấy căn đang cho thuê phù hợp với các tiêu chí.",
                {"properties": [], "total": 0},
            )
        return _result(
            True,
            "OK",
            f"Tìm thấy {len(matches)} căn phù hợp.",
            {
                "properties": selected,
                "total": len(matches),
                "returned": len(selected),
            },
        )

    def get_property_details(self, property_id: str) -> ToolResult:
        """Return current, grounded details for one rental.

        Args:
            property_id: Inventory id such as ``HN-CG-001``.

        Returns:
            ``ToolResult`` with one full property object.

        Errors:
            ``INVALID_ARGUMENT`` for an empty/non-string id and ``NOT_FOUND``
            when no inventory record has that id.

        Side effects:
            None.
        """
        if not isinstance(property_id, str) or not property_id.strip():
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Mã căn không được để trống.",
            )
        property_item = self.store.get_property(property_id.strip().upper())
        if property_item is None:
            return _result(
                False,
                "NOT_FOUND",
                f"Không tìm thấy căn có mã {property_id.strip()}.",
                {"property_id": property_id.strip()},
            )
        return _result(
            True,
            "OK",
            f"Đã lấy thông tin căn {property_item['property_id']}.",
            {"property": property_item},
        )

    def compare_properties(self, property_ids: list[str]) -> ToolResult:
        """Compare two or three rentals using deterministic inventory values.

        Args:
            property_ids: Two or three distinct property ids.

        Returns:
            ``ToolResult`` containing properties in caller order, calculated
            deposit amounts, and ids for lowest price/largest area/lowest
            deposit.

        Errors:
            ``INVALID_ARGUMENT`` for a malformed selection and ``NOT_FOUND``
            when any requested id is absent.

        Side effects:
            None.
        """
        if (
            not isinstance(property_ids, list)
            or not 2 <= len(property_ids) <= 3
            or not all(isinstance(item, str) and item.strip() for item in property_ids)
        ):
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Cần cung cấp danh sách từ 2 đến 3 mã căn.",
            )
        normalized_ids = [item.strip().upper() for item in property_ids]
        if len(set(normalized_ids)) != len(normalized_ids):
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Các mã căn dùng để so sánh phải khác nhau.",
            )

        properties: list[dict[str, Any]] = []
        missing_ids: list[str] = []
        for property_id in normalized_ids:
            property_item = self.store.get_property(property_id)
            if property_item is None:
                missing_ids.append(property_id)
                continue
            comparison_item = dict(property_item)
            comparison_item["deposit_vnd"] = int(
                property_item["price_vnd"] * property_item["deposit_months"]
            )
            comparison_item["initial_payment_vnd"] = (
                comparison_item["deposit_vnd"] + property_item["price_vnd"]
            )
            properties.append(comparison_item)

        if missing_ids:
            return _result(
                False,
                "NOT_FOUND",
                "Một hoặc nhiều mã căn không tồn tại.",
                {"missing_property_ids": missing_ids},
            )

        lowest_price = min(
            properties, key=lambda item: (item["price_vnd"], item["property_id"])
        )
        largest_area = max(
            properties, key=lambda item: (item["area_m2"], item["property_id"])
        )
        lowest_deposit = min(
            properties, key=lambda item: (item["deposit_vnd"], item["property_id"])
        )
        return _result(
            True,
            "OK",
            f"Đã so sánh {len(properties)} căn.",
            {
                "properties": properties,
                "highlights": {
                    "lowest_price_property_id": lowest_price["property_id"],
                    "largest_area_property_id": largest_area["property_id"],
                    "lowest_deposit_property_id": lowest_deposit["property_id"],
                },
            },
        )

    def get_available_viewing_slots(
        self,
        property_id: str,
        date: str | None = None,
        time_of_day: str | None = None,
    ) -> ToolResult:
        """List unbooked viewing times for a rental.

        Args:
            property_id: Inventory id to view.
            date: Optional Vietnam local date in ``YYYY-MM-DD`` format.
            time_of_day: Optional ``sáng``, ``chiều``, or ``tối`` filter
                (English equivalents are also accepted).

        Returns:
            ``ToolResult`` with chronological, unbooked slot objects.

        Errors:
            ``INVALID_ARGUMENT`` for bad ids/dates/day-parts, ``NOT_FOUND`` for
            an unknown property, and ``SLOT_UNAVAILABLE`` if no matching slot
            is currently bookable.

        Side effects:
            None.
        """
        if not isinstance(property_id, str) or not property_id.strip():
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Mã căn không được để trống.",
            )
        normalized_id = property_id.strip().upper()
        property_item = self.store.get_property(normalized_id)
        if property_item is None:
            return _result(
                False,
                "NOT_FOUND",
                f"Không tìm thấy căn có mã {normalized_id}.",
                {"property_id": normalized_id},
            )
        if not property_item["available"]:
            return _result(
                False,
                "SLOT_UNAVAILABLE",
                f"Căn {normalized_id} hiện không còn nhận lịch xem.",
                {"property_id": normalized_id, "slots": [], "total": 0},
            )

        date_text: str | None = None
        if date is not None:
            if not isinstance(date, str):
                return _result(
                    False,
                    "INVALID_ARGUMENT",
                    "Ngày xem phải có định dạng YYYY-MM-DD.",
                )
            try:
                requested_date = datetime.strptime(date.strip(), "%Y-%m-%d").date()
            except ValueError:
                return _result(
                    False,
                    "INVALID_ARGUMENT",
                    "Ngày xem phải là ngày hợp lệ theo định dạng YYYY-MM-DD.",
                )
            if requested_date <= self.store.local_today():
                return _result(
                    False,
                    "INVALID_ARGUMENT",
                    "Ngày xem phải sau ngày hiện tại.",
                )
            date_text = requested_date.isoformat()

        period: str | None = None
        if time_of_day is not None:
            if not isinstance(time_of_day, str) or not time_of_day.strip():
                return _result(
                    False,
                    "INVALID_ARGUMENT",
                    "Buổi xem phải là sáng, chiều hoặc tối.",
                )
            period_aliases = {
                "sang": "morning",
                "buoi sang": "morning",
                "morning": "morning",
                "chieu": "afternoon",
                "buoi chieu": "afternoon",
                "afternoon": "afternoon",
                "toi": "evening",
                "buoi toi": "evening",
                "evening": "evening",
            }
            period = period_aliases.get(_normalized_text(time_of_day))
            if period is None:
                return _result(
                    False,
                    "INVALID_ARGUMENT",
                    "Buổi xem phải là sáng, chiều hoặc tối.",
                )

        slots: list[dict[str, str]] = []
        for slot in self.store.list_available_slots(normalized_id, date_text):
            starts_at = datetime.fromisoformat(slot["starts_at"])
            hour = starts_at.hour
            slot_period = (
                "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
            )
            if period is not None and slot_period != period:
                continue
            slots.append(
                {
                    **slot,
                    "date": starts_at.date().isoformat(),
                    "time": starts_at.strftime("%H:%M"),
                    "time_of_day": slot_period,
                }
            )

        if not slots:
            return _result(
                False,
                "SLOT_UNAVAILABLE",
                "Không còn lịch xem phù hợp với ngày hoặc buổi đã chọn.",
                {
                    "property_id": normalized_id,
                    "slots": [],
                    "total": 0,
                },
            )
        return _result(
            True,
            "OK",
            f"Căn {normalized_id} còn {len(slots)} lịch xem phù hợp.",
            {
                "property_id": normalized_id,
                "slots": slots,
                "total": len(slots),
            },
        )

    def book_viewing(
        self,
        property_id: str,
        slot_id: str,
        viewer_name: str,
        viewer_phone: str,
        *,
        session_id: str | None = None,
    ) -> ToolResult:
        """Reserve one viewing slot after the executor's confirmation gate.

        Args:
            property_id: Confirmed property id.
            slot_id: Confirmed available slot id.
            viewer_name: Confirmed viewer display name.
            viewer_phone: Vietnam mobile number; ``+84`` and local forms work.
            session_id: Hidden session id injected by the trusted executor,
                never selected by the model.

        Returns:
            ``ToolResult`` containing the confirmed booking with a masked phone.

        Errors:
            ``CONFIRMATION_REQUIRED`` if the executor did not inject a session,
            ``INVALID_ARGUMENT`` for malformed user data, ``NOT_FOUND`` for an
            unknown property, ``SLOT_UNAVAILABLE`` for a mismatched slot, and
            ``CONFLICT`` if another request already reserved it.

        Side effects:
            On success, atomically inserts one SQLite booking. Failed calls do
            not change the database.
        """
        if not isinstance(session_id, str) or not session_id.strip():
            return _result(
                False,
                "CONFIRMATION_REQUIRED",
                "Cần xác nhận lịch xem trong phiên hiện tại trước khi đặt.",
            )
        if not isinstance(property_id, str) or not property_id.strip():
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Mã căn không được để trống.",
            )
        if not isinstance(slot_id, str) or not slot_id.strip():
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Mã khung giờ không được để trống.",
            )
        if not isinstance(viewer_name, str):
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Tên người xem không hợp lệ.",
            )
        normalized_name = " ".join(viewer_name.split())
        if not 2 <= len(normalized_name) <= 80:
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Tên người xem phải có từ 2 đến 80 ký tự.",
            )
        normalized_phone = _normalize_vietnam_phone(viewer_phone)
        if normalized_phone is None:
            return _result(
                False,
                "INVALID_ARGUMENT",
                "Số điện thoại Việt Nam không hợp lệ.",
            )

        normalized_id = property_id.strip().upper()
        normalized_slot_id = slot_id.strip().upper()
        try:
            booking = self.store.create_booking(
                session_id=session_id.strip(),
                property_id=normalized_id,
                slot_id=normalized_slot_id,
                viewer_name=normalized_name,
                viewer_phone=normalized_phone,
            )
        except RentalStoreError as exc:
            return _result(False, exc.code, exc.message, exc.data)

        safe_booking = dict(booking)
        safe_booking["viewer_phone"] = _mask_phone(booking["viewer_phone"])
        return _result(
            True,
            "OK",
            "Đã đặt lịch xem nhà thành công.",
            {"booking": safe_booking},
        )


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_properties": {
        "name": "search_properties",
        "description": "Tìm nhà trọ/căn hộ đang trống theo vị trí, giá và tiện ích.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "district": {"type": "string"},
                "max_price_vnd": {"type": "number", "exclusiveMinimum": 0},
                "property_type": {"type": "string"},
                "min_area_m2": {"type": "number", "exclusiveMinimum": 0},
                "amenities": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["city"],
            "additionalProperties": False,
        },
    },
    "get_property_details": {
        "name": "get_property_details",
        "description": "Lấy dữ liệu chi tiết hiện tại của một căn theo mã căn.",
        "parameters": {
            "type": "object",
            "properties": {"property_id": {"type": "string"}},
            "required": ["property_id"],
            "additionalProperties": False,
        },
    },
    "compare_properties": {
        "name": "compare_properties",
        "description": "So sánh 2–3 căn theo giá, diện tích và tiền cọc.",
        "parameters": {
            "type": "object",
            "properties": {
                "property_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "maxItems": 3,
                    "uniqueItems": True,
                }
            },
            "required": ["property_ids"],
            "additionalProperties": False,
        },
    },
    "get_available_viewing_slots": {
        "name": "get_available_viewing_slots",
        "description": "Tra các khung giờ xem nhà còn trống theo ngày và buổi.",
        "parameters": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "date": {"type": "string", "format": "date"},
                "time_of_day": {
                    "type": "string",
                    "enum": ["sáng", "chiều", "tối"],
                },
            },
            "required": ["property_id"],
            "additionalProperties": False,
        },
    },
    "book_viewing": {
        "name": "book_viewing",
        "description": "Đặt một lịch xem đã được người dùng xác nhận.",
        "parameters": {
            "type": "object",
            "properties": {
                "property_id": {"type": "string"},
                "slot_id": {"type": "string"},
                "viewer_name": {"type": "string", "minLength": 2, "maxLength": 80},
                "viewer_phone": {"type": "string"},
            },
            "required": [
                "property_id",
                "slot_id",
                "viewer_name",
                "viewer_phone",
            ],
            "additionalProperties": False,
        },
    },
}

# Metadata only. Runtime callables are created explicitly with a bound store.
AVAILABLE_TOOLS = TOOL_SCHEMAS


def create_tool_registry(
    store: RentalStore,
) -> dict[str, Callable[..., ToolResult]]:
    """Bind tool callables to ``store`` without opening a DB at import time."""
    tools = RentalTools(store)
    return {
        "search_properties": tools.search_properties,
        "get_property_details": tools.get_property_details,
        "compare_properties": tools.compare_properties,
        "get_available_viewing_slots": tools.get_available_viewing_slots,
        "book_viewing": tools.book_viewing,
    }
