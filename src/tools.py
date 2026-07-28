"""
🛠️ TOOL REGISTRY & CRUD LAYER (Dành cho Role 2: Tool & Spec Engineer)

Nơi khai báo tất cả các "món đồ nghề" mà ReAct Agent có thể gọi để làm việc với
kho dữ liệu nhà trọ / căn hộ cho thuê tại `data/listings.json`.

Nguyên tắc thiết kế (bám theo checklist Mốc 2 & Mốc 3):
  1. Mọi tool đều trả về **chuỗi tiếng Việt dễ đọc** để Agent đưa thẳng vào Observation.
  2. Mọi tool **không bao giờ raise Exception** — gặp lỗi thì trả về chuỗi bắt đầu bằng "LỖI:".
  3. Đầy đủ CRUD: Create (tạo tin), Read (tìm/xem), Update (sửa), Delete (xoá)
     + nghiệp vụ đặt lịch xem nhà (book / cancel).
"""

from __future__ import annotations

import functools
import json
import os
import random
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

# --------------------------------------------------------------------------- #
# ⚙️ CẤU HÌNH
# --------------------------------------------------------------------------- #

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.environ.get("LISTINGS_DATA_PATH") or os.path.join(BASE_DIR, "data", "listings.json")

MAX_RESULTS = 5           # 🛡️ Guardrail: chặn Agent nuốt cả 50 tin vào context
FURNISHING_LEVELS = ("full", "basic", "empty")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")

_DATA: Optional[Dict[str, Any]] = None


# --------------------------------------------------------------------------- #
# 🔌 TẦNG TRUY CẬP DỮ LIỆU (private helpers)
# --------------------------------------------------------------------------- #

def _load(force: bool = False) -> Dict[str, Any]:
    """Đọc toàn bộ dataset vào bộ nhớ (có cache để không đọc đĩa mỗi lần gọi tool)."""
    global _DATA
    if _DATA is None or force:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            _DATA = json.load(f)
        _DATA.setdefault("meta", {})
        _DATA.setdefault("listings", [])
        _DATA.setdefault("bookings", [])
    return _DATA


def _save(data: Dict[str, Any]) -> None:
    """Ghi dataset xuống đĩa an toàn (ghi file tạm rồi thay thế nguyên tử)."""
    data["meta"]["total_listings"] = len(data["listings"])
    tmp_path = DATA_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, DATA_PATH)


def reload_data() -> str:
    """Nạp lại dữ liệu từ đĩa, huỷ cache (dùng khi file bị sửa bên ngoài)."""
    _load(force=True)
    return f"✅ Đã nạp lại {len(_load()['listings'])} tin đăng từ {os.path.basename(DATA_PATH)}."


def _tool(fn):
    """Decorator 🛡️: bọc tool để lỗi trở thành chuỗi thông báo thay vì crash Agent."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as err:            # Lỗi nghiệp vụ / tham số sai
            return f"LỖI: {err}"
        except FileNotFoundError:
            return f"LỖI: Không tìm thấy kho dữ liệu tại '{DATA_PATH}'."
        except Exception as err:             # Lỗi ngoài dự kiến
            return f"LỖI HỆ THỐNG khi chạy '{fn.__name__}': {type(err).__name__} - {err}"

    return wrapper


def _norm(text: Any) -> str:
    """Chuẩn hoá chuỗi tiếng Việt: bỏ dấu, bỏ ký tự đặc biệt, viết thường.

    Ví dụ: 'TP.HCM' -> 'tphcm', 'Cầu Giấy' -> 'caugiay', 'Đống Đa' -> 'dongda'.
    """
    if text is None:
        return ""
    s = unicodedata.normalize("NFD", str(text))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = s.replace("đ", "d").replace("Đ", "D")
    return re.sub(r"[^a-z0-9]", "", s.lower())


_CITY_ALIASES = {
    "hanoi": "Hà Nội", "hn": "Hà Nội", "thudo": "Hà Nội",
    "tphcm": "TP.HCM", "hcm": "TP.HCM", "sg": "TP.HCM", "saigon": "TP.HCM",
    "hochiminh": "TP.HCM", "tphochiminh": "TP.HCM", "thanhphohochiminh": "TP.HCM",
    "danang": "Đà Nẵng", "dn": "Đà Nẵng",
}


def _resolve_city(value: Any) -> Optional[str]:
    """Ánh xạ tên thành phố người dùng gõ tự do về đúng tên chuẩn trong dataset."""
    key = _norm(value)
    if not key:
        return None
    if key in _CITY_ALIASES:
        return _CITY_ALIASES[key]
    for city in _load()["meta"].get("cities", []):
        if _norm(city) == key or key in _norm(city) or _norm(city) in key:
            return city
    return None


def _find_listing(listing_id: Any) -> Optional[Dict[str, Any]]:
    """Tìm 1 tin đăng theo mã (không phân biệt hoa thường, dấu gạch)."""
    key = _norm(listing_id)
    if not key:
        return None
    for listing in _load()["listings"]:
        if _norm(listing.get("id")) == key:
            return listing
    return None


def _as_list(value: Union[str, List[str], None]) -> List[str]:
    """Nhận 'wifi, dieu_hoa' hoặc ['wifi', 'dieu_hoa'] -> luôn trả về list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.replace(";", ",").split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


def _as_dict(value: Union[str, Dict[str, Any], None]) -> Dict[str, Any]:
    """Nhận dict hoặc chuỗi JSON (LLM hay truyền JSON string) -> luôn trả về dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as err:
            raise ValueError(f"Tham số phải là JSON hợp lệ ({err.msg}).") from err
        if not isinstance(parsed, dict):
            raise ValueError("Tham số JSON phải là một object dạng {\"trường\": \"giá trị\"}.")
        return parsed
    raise ValueError("Tham số cập nhật không hợp lệ, cần dict hoặc chuỗi JSON.")


def _make_listing_id(city: str, district: str) -> str:
    """Sinh mã tin mới theo quy ước dataset: <MÃ TP>-<MÃ QUẬN>-<SỐ THỨ TỰ>.

    Ví dụ: Hà Nội + Cầu Giấy -> 'HN-CG-003'; TP.HCM + Quận 7 -> 'SG-Q7-002'.
    """
    city_code = {"Hà Nội": "HN", "TP.HCM": "SG", "Đà Nẵng": "DN"}.get(city, "XX")
    # Lấy chữ cái đầu của từng từ trong tên quận (đã bỏ dấu): 'Nam Từ Liêm' -> 'NTL' -> 'NT'
    words = re.sub(r"[^A-Za-z0-9 ]", " ", _strip_accents(district)).split()
    initials = "".join(w[0].upper() for w in words)
    district_code = (initials or "XX")[:2].ljust(2, "X")

    prefix = f"{city_code}-{district_code}-"
    existing = [l["id"] for l in _load()["listings"] if str(l.get("id", "")).startswith(prefix)]
    next_no = 1
    for listing_id in existing:
        try:
            next_no = max(next_no, int(str(listing_id).rsplit("-", 1)[-1]) + 1)
        except ValueError:
            continue
    return f"{prefix}{next_no:03d}"


def _strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt nhưng giữ nguyên khoảng trắng & hoa thường."""
    s = unicodedata.normalize("NFD", str(text))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D")


# --------------------------------------------------------------------------- #
# 🎨 ĐỊNH DẠNG HIỂN THỊ
# --------------------------------------------------------------------------- #

def _fmt_vnd(amount: Any) -> str:
    """1700000 -> '1.700.000đ'"""
    try:
        return f"{int(amount):,}".replace(",", ".") + "đ"
    except (TypeError, ValueError):
        return str(amount)


def _summary(listing: Dict[str, Any]) -> str:
    """Một dòng tóm tắt tin đăng dùng cho danh sách kết quả tìm kiếm."""
    loc = listing.get("location", {})
    distance = loc.get("distance_to_city_center_km")
    distance_text = f"cách trung tâm {distance}km" if distance is not None else "chưa rõ khoảng cách"
    return (
        f"[{listing.get('id')}] {listing.get('title')}\n"
        f"    💰 {_fmt_vnd(listing.get('price_vnd_month'))}/tháng"
        f" · 📐 {listing.get('area_m2')}m² · 🛏 {listing.get('bedrooms')}PN"
        f" · ⭐ {listing.get('rating')} ({listing.get('review_count')} đánh giá)\n"
        f"    📍 {loc.get('district')}, {loc.get('city')}"
        f" · {distance_text}"
        f" · trạng thái: {listing.get('status')}"
    )


def _detail(listing: Dict[str, Any]) -> str:
    """Khối mô tả đầy đủ 1 tin đăng."""
    loc = listing.get("location", {})
    util = listing.get("utilities", {})
    rules = listing.get("rules", {})
    landlord = listing.get("landlord", {})
    amenity_vocab = _load()["meta"].get("amenity_vocabulary", {})
    amenities = ", ".join(amenity_vocab.get(a, a) for a in listing.get("amenities", [])) or "Không có"
    free_slots = [s for s in listing.get("viewing_slots", []) if s.get("status") == "available"]

    return "\n".join([
        f"🏠 {listing.get('title')}  (mã: {listing.get('id')})",
        f"   Loại hình     : {listing.get('property_type_label')} · Nội thất: {listing.get('furnishing')}",
        f"   Giá thuê      : {_fmt_vnd(listing.get('price_vnd_month'))}/tháng"
        f" · Cọc {listing.get('deposit_months')} tháng"
        f" · Thuê tối thiểu {listing.get('min_lease_months')} tháng",
        f"   Diện tích     : {listing.get('area_m2')}m² · {listing.get('bedrooms')}PN"
        f" · {listing.get('bathrooms')}WC · Tầng {listing.get('floor')}/{listing.get('total_floors')}"
        f" · Tối đa {listing.get('max_occupants')} người",
        f"   Địa chỉ       : {loc.get('full_address')}",
        f"   Tiện nghi     : {amenities}",
        f"   Chi phí khác  : Điện {_fmt_vnd(util.get('electricity_vnd_per_kwh'))}/kWh"
        f" · Nước {_fmt_vnd(util.get('water_vnd_per_m3'))} ({util.get('water_charge_mode')})"
        f" · Internet {_fmt_vnd(util.get('internet_vnd_month'))}/tháng"
        f" · Dịch vụ {_fmt_vnd(util.get('service_fee_vnd_month'))}/tháng"
        f" · Gửi xe máy {_fmt_vnd(util.get('motorbike_parking_vnd_month'))}/tháng",
        f"   Nội quy       : Thú cưng: {'có' if rules.get('pets_allowed') else 'không'}"
        f" · Nấu ăn: {'có' if rules.get('cooking_allowed') else 'không'}"
        f" · Chung chủ: {'có' if rules.get('shared_with_owner') else 'không'}"
        f" · Giờ giới nghiêm: {rules.get('curfew') or 'tự do'}"
        f" · Sinh viên: {'chào đón' if rules.get('students_welcome') else 'không ưu tiên'}",
        f"   Chủ nhà       : {landlord.get('name')} · ☎ {landlord.get('phone')}"
        f" · {'đã xác minh' if landlord.get('verified') else 'chưa xác minh'}"
        f" · phản hồi ~{landlord.get('avg_response_minutes')} phút",
        f"   Trạng thái    : {listing.get('status')} · Vào ở từ {listing.get('available_from')}",
        f"   Lịch xem trống: {len(free_slots)}/{len(listing.get('viewing_slots', []))} khung giờ",
        f"   Mô tả         : {listing.get('description')}",
    ])


def _slot_line(slot: Dict[str, Any]) -> str:
    mark = "🟢 còn trống" if slot.get("status") == "available" else f"🔴 đã đặt ({slot.get('booked_by')})"
    return (f"    - {slot.get('slot_id')} | {slot.get('date')} lúc {slot.get('time')}"
            f" ({slot.get('duration_minutes')} phút) | {mark}")


# --------------------------------------------------------------------------- #
# ✅ VALIDATION
# --------------------------------------------------------------------------- #

def _validate_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Kiểm tra & chuẩn hoá các trường của tin đăng. Raise ValueError nếu sai."""
    meta = _load()["meta"]
    clean = dict(fields)

    if "property_type" in clean:
        types = meta.get("property_types", {})
        if clean["property_type"] not in types:
            raise ValueError(
                f"Loại hình '{clean['property_type']}' không hợp lệ. "
                f"Chọn 1 trong: {', '.join(types)}."
            )
        clean["property_type_label"] = types[clean["property_type"]]

    if "status" in clean:
        statuses = meta.get("status_vocabulary", {})
        if clean["status"] not in statuses:
            raise ValueError(
                f"Trạng thái '{clean['status']}' không hợp lệ. Chọn 1 trong: {', '.join(statuses)}."
            )

    if "furnishing" in clean and clean["furnishing"] not in FURNISHING_LEVELS:
        raise ValueError(
            f"Mức nội thất '{clean['furnishing']}' không hợp lệ. "
            f"Chọn 1 trong: {', '.join(FURNISHING_LEVELS)}."
        )

    if "amenities" in clean:
        vocab = meta.get("amenity_vocabulary", {})
        clean["amenities"] = sorted(set(_as_list(clean["amenities"])))
        unknown = [a for a in clean["amenities"] if a not in vocab]
        if unknown:
            raise ValueError(
                f"Tiện nghi không có trong từ điển: {', '.join(unknown)}. "
                f"Hợp lệ: {', '.join(vocab)}."
            )

    for field in ("price_vnd_month", "area_m2", "max_occupants"):
        if field in clean:
            try:
                value = float(clean[field])
            except (TypeError, ValueError):
                raise ValueError(f"Trường '{field}' phải là số, nhận được '{clean[field]}'.")
            if value <= 0:
                raise ValueError(f"Trường '{field}' phải lớn hơn 0.")
            clean[field] = int(value) if float(value).is_integer() else value

    for field in ("bedrooms", "bathrooms", "floor", "total_floors",
                  "deposit_months", "min_lease_months", "review_count"):
        if field in clean:
            try:
                clean[field] = int(clean[field])
            except (TypeError, ValueError):
                raise ValueError(f"Trường '{field}' phải là số nguyên.")
            if clean[field] < 0:
                raise ValueError(f"Trường '{field}' không được âm.")

    if "rating" in clean:
        try:
            clean["rating"] = round(float(clean["rating"]), 1)
        except (TypeError, ValueError):
            raise ValueError("Trường 'rating' phải là số từ 0 đến 5.")
        if not 0 <= clean["rating"] <= 5:
            raise ValueError("Trường 'rating' phải nằm trong khoảng 0 - 5.")

    for field in ("available_from", "posted_at", "updated_at"):
        if field in clean and clean[field] and not DATE_RE.match(str(clean[field])):
            raise ValueError(f"Trường '{field}' phải theo định dạng YYYY-MM-DD.")

    return clean


def _validate_datetime(date: str, time: str) -> None:
    if not DATE_RE.match(str(date)):
        raise ValueError(f"Ngày '{date}' sai định dạng, cần YYYY-MM-DD (ví dụ 2026-08-05).")
    if not TIME_RE.match(str(time)):
        raise ValueError(f"Giờ '{time}' sai định dạng, cần HH:MM (ví dụ 19:00).")
    try:
        datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError(f"Thời điểm '{date} {time}' không tồn tại trên lịch.")


# --------------------------------------------------------------------------- #
# 📖 READ — Đọc & tìm kiếm
# --------------------------------------------------------------------------- #

@_tool
def search_listings(
    city: Optional[str] = None,
    district: Optional[str] = None,
    max_price: Optional[Union[int, str]] = None,
    min_price: Optional[Union[int, str]] = None,
    property_type: Optional[str] = None,
    min_area: Optional[Union[int, str]] = None,
    bedrooms: Optional[Union[int, str]] = None,
    amenities: Optional[Union[str, List[str]]] = None,
    furnishing: Optional[str] = None,
    status: Optional[str] = "available",
    students_welcome: Optional[bool] = None,
    pets_allowed: Optional[bool] = None,
    near: Optional[str] = None,
    sort_by: str = "price",
    max_results: int = MAX_RESULTS,
) -> str:
    """
    [READ] Tìm phòng trọ / căn hộ cho thuê theo bộ lọc của khách.

    Args:
        city (str): Thành phố — 'Hà Nội', 'TP.HCM', 'Đà Nẵng' (chấp nhận cả 'HCM', 'saigon').
        district (str): Quận/huyện, ví dụ 'Cầu Giấy', 'Thủ Đức' (không cần dấu).
        max_price (int): Ngân sách tối đa mỗi tháng (VNĐ).
        min_price (int): Giá tối thiểu mỗi tháng (VNĐ).
        property_type (str): Mã loại hình: phong_tro, chung_cu_mini, studio,
            can_ho_dich_vu, can_ho_chung_cu, nha_nguyen_can.
        min_area (int): Diện tích tối thiểu (m²).
        bedrooms (int): Số phòng ngủ tối thiểu.
        amenities (list|str): Tiện nghi bắt buộc, ví dụ 'dieu_hoa, may_giat'.
        furnishing (str): Mức nội thất: full / basic / empty.
        status (str): Lọc theo trạng thái tin, mặc định 'available'. Truyền 'all' để bỏ lọc.
        students_welcome (bool): Chỉ lấy nhà nhận sinh viên.
        pets_allowed (bool): Chỉ lấy nhà cho nuôi thú cưng.
        near (str): Từ khoá địa điểm gần đó / tên đường, ví dụ 'ĐH Bách Khoa'.
        sort_by (str): price | price_desc | rating | area | distance.
        max_results (int): Số kết quả tối đa trả về (mặc định 5).

    Returns:
        str: Danh sách tin đăng phù hợp (đã đánh số), hoặc thông báo không tìm thấy.
    """
    listings = list(_load()["listings"])

    if city:
        resolved = _resolve_city(city)
        if not resolved:
            available = ", ".join(_load()["meta"].get("cities", []))
            return f"LỖI: Chưa có dữ liệu cho thành phố '{city}'. Hiện chỉ hỗ trợ: {available}."
        listings = [l for l in listings if l["location"]["city"] == resolved]

    if district:
        key = _norm(district)
        listings = [l for l in listings if key in _norm(l["location"]["district"])]

    if status and str(status).lower() != "all":
        listings = [l for l in listings if l.get("status") == status]

    if property_type:
        listings = [l for l in listings if l.get("property_type") == property_type]

    if max_price is not None:
        limit = float(max_price)
        listings = [l for l in listings if l["price_vnd_month"] <= limit]

    if min_price is not None:
        floor_price = float(min_price)
        listings = [l for l in listings if l["price_vnd_month"] >= floor_price]

    if min_area is not None:
        area = float(min_area)
        listings = [l for l in listings if l["area_m2"] >= area]

    if bedrooms is not None:
        rooms = int(bedrooms)
        listings = [l for l in listings if l["bedrooms"] >= rooms]

    required = _as_list(amenities)
    if required:
        listings = [l for l in listings if set(required).issubset(set(l.get("amenities", [])))]

    if furnishing:
        listings = [l for l in listings if l.get("furnishing") == furnishing]

    if students_welcome is not None:
        listings = [l for l in listings if l["rules"].get("students_welcome") is bool(students_welcome)]

    if pets_allowed is not None:
        listings = [l for l in listings if l["rules"].get("pets_allowed") is bool(pets_allowed)]

    if near:
        key = _norm(near)
        def _matches_near(l: Dict[str, Any]) -> bool:
            haystack = [p.get("name", "") for p in l.get("nearby_places", [])]
            haystack += [l["location"].get("street", ""), l["location"].get("ward", "")]
            return any(key in _norm(item) for item in haystack)
        listings = [l for l in listings if _matches_near(l)]

    sorters = {
        "price": lambda l: l["price_vnd_month"],
        "price_desc": lambda l: -l["price_vnd_month"],
        "rating": lambda l: -l["rating"],
        "area": lambda l: -l["area_m2"],
        # Tin mới tạo chưa có toạ độ -> đẩy xuống cuối danh sách thay vì gây lỗi so sánh None
        "distance": lambda l: l["location"].get("distance_to_city_center_km") or 999,
    }
    listings.sort(key=sorters.get(sort_by, sorters["price"]))

    if not listings:
        return "Không tìm thấy tin đăng nào khớp với yêu cầu. Hãy thử nới ngân sách hoặc đổi khu vực."

    try:
        limit = max(1, int(max_results))
    except (TypeError, ValueError):
        limit = MAX_RESULTS

    shown = listings[:limit]
    header = f"🔎 Tìm thấy {len(listings)} tin phù hợp (hiển thị {len(shown)} tin):"
    body = "\n".join(f"{i}. {_summary(l)}" for i, l in enumerate(shown, 1))
    footer = "" if len(listings) <= limit else f"\n… còn {len(listings) - limit} tin nữa, hãy lọc thêm cho gọn."
    return f"{header}\n{body}{footer}"


@_tool
def get_listing(listing_id: str) -> str:
    """
    [READ] Xem chi tiết đầy đủ một tin đăng theo mã.

    Args:
        listing_id (str): Mã tin đăng, ví dụ 'HN-CG-001'.

    Returns:
        str: Thông tin chi tiết (giá, diện tích, tiện nghi, nội quy, chủ nhà, lịch xem).
    """
    listing = _find_listing(listing_id)
    if not listing:
        return f"LỖI: Không tìm thấy tin đăng nào có mã '{listing_id}'."
    return _detail(listing)


@_tool
def list_viewing_slots(listing_id: str, only_available: bool = True) -> str:
    """
    [READ] Liệt kê các khung giờ có thể đi xem nhà của một tin đăng.

    Args:
        listing_id (str): Mã tin đăng, ví dụ 'SG-TD-001'.
        only_available (bool): True = chỉ hiện khung giờ còn trống (mặc định).

    Returns:
        str: Danh sách khung giờ kèm mã slot để đặt lịch.
    """
    listing = _find_listing(listing_id)
    if not listing:
        return f"LỖI: Không tìm thấy tin đăng nào có mã '{listing_id}'."

    slots = listing.get("viewing_slots", [])
    if only_available:
        slots = [s for s in slots if s.get("status") == "available"]
    if not slots:
        return (f"Tin {listing['id']} hiện không có khung giờ xem nhà nào"
                f"{' còn trống' if only_available else ''}. "
                f"Có thể liên hệ trực tiếp chủ nhà: {listing['landlord']['name']} "
                f"- {listing['landlord']['phone']}.")

    slots = sorted(slots, key=lambda s: (s.get("date", ""), s.get("time", "")))
    lines = "\n".join(_slot_line(s) for s in slots)
    return f"🗓️ Lịch xem nhà của tin {listing['id']} ({len(slots)} khung giờ):\n{lines}"


@_tool
def list_bookings(customer_phone: Optional[str] = None, listing_id: Optional[str] = None) -> str:
    """
    [READ] Xem các lịch hẹn xem nhà đã đặt.

    Args:
        customer_phone (str): Lọc theo số điện thoại khách (tuỳ chọn).
        listing_id (str): Lọc theo mã tin đăng (tuỳ chọn).

    Returns:
        str: Danh sách lịch hẹn kèm mã booking để huỷ khi cần.
    """
    bookings = list(_load()["bookings"])
    if customer_phone:
        key = _norm(customer_phone)
        bookings = [b for b in bookings if _norm(b.get("customer_phone")) == key]
    if listing_id:
        key = _norm(listing_id)
        bookings = [b for b in bookings if _norm(b.get("listing_id")) == key]

    if not bookings:
        return "Chưa có lịch hẹn xem nhà nào khớp với điều kiện."

    lines = []
    for b in sorted(bookings, key=lambda x: (x.get("date", ""), x.get("time", ""))):
        lines.append(
            f"    - {b.get('booking_id')} | tin {b.get('listing_id')} | "
            f"{b.get('date')} lúc {b.get('time')} | {b.get('customer_name')} "
            f"({b.get('customer_phone')}) | {b.get('status')}"
        )
    return f"📒 Có {len(bookings)} lịch hẹn:\n" + "\n".join(lines)


# --------------------------------------------------------------------------- #
# ➕ CREATE — Thêm mới
# --------------------------------------------------------------------------- #

@_tool
def create_listing(
    title: str,
    city: str,
    district: str,
    price_vnd_month: Union[int, str],
    area_m2: Union[int, str],
    property_type: str = "phong_tro",
    bedrooms: Union[int, str] = 1,
    bathrooms: Union[int, str] = 1,
    landlord_name: str = "Chưa cập nhật",
    landlord_phone: str = "",
    amenities: Optional[Union[str, List[str]]] = None,
    furnishing: str = "basic",
    description: str = "",
    available_from: Optional[str] = None,
    extra: Optional[Union[str, Dict[str, Any]]] = None,
) -> str:
    """
    [CREATE] Đăng một tin cho thuê mới vào kho dữ liệu.

    Args:
        title (str): Tiêu đề tin đăng.
        city (str): Thành phố ('Hà Nội', 'TP.HCM', 'Đà Nẵng').
        district (str): Quận/huyện.
        price_vnd_month (int): Giá thuê mỗi tháng (VNĐ).
        area_m2 (int): Diện tích (m²).
        property_type (str): Mã loại hình, mặc định 'phong_tro'.
        bedrooms (int): Số phòng ngủ.
        bathrooms (int): Số phòng tắm.
        landlord_name (str): Tên chủ nhà.
        landlord_phone (str): Số điện thoại chủ nhà.
        amenities (list|str): Danh sách mã tiện nghi.
        furnishing (str): full / basic / empty.
        description (str): Mô tả chi tiết.
        available_from (str): Ngày có thể vào ở (YYYY-MM-DD), mặc định hôm nay.
        extra (dict|str JSON): Các trường nâng cao ghi đè (utilities, rules, location…).

    Returns:
        str: Xác nhận kèm mã tin vừa tạo, hoặc thông báo lỗi kiểm tra dữ liệu.
    """
    if not str(title).strip():
        raise ValueError("Tiêu đề tin đăng không được để trống.")

    resolved_city = _resolve_city(city)
    if not resolved_city:
        available = ", ".join(_load()["meta"].get("cities", []))
        raise ValueError(f"Thành phố '{city}' không được hỗ trợ. Hiện có: {available}.")
    if not str(district).strip():
        raise ValueError("Quận/huyện không được để trống.")

    today = datetime.now().strftime("%Y-%m-%d")
    fields = _validate_fields({
        "property_type": property_type,
        "price_vnd_month": price_vnd_month,
        "area_m2": area_m2,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "furnishing": furnishing,
        "amenities": _as_list(amenities),
        "available_from": available_from or today,
    })

    data = _load()
    new_id = _make_listing_id(resolved_city, district)
    listing: Dict[str, Any] = {
        "id": new_id,
        "title": str(title).strip(),
        "property_type": fields["property_type"],
        "property_type_label": fields["property_type_label"],
        "status": "available",
        "price_vnd_month": fields["price_vnd_month"],
        "deposit_months": 1,
        "min_lease_months": 6,
        "area_m2": fields["area_m2"],
        "bedrooms": fields["bedrooms"],
        "bathrooms": fields["bathrooms"],
        "floor": 1,
        "total_floors": 1,
        "max_occupants": max(1, fields["bedrooms"] * 2),
        "furnishing": fields["furnishing"],
        "amenities": fields["amenities"],
        "utilities": {
            "electricity_vnd_per_kwh": 3500,
            "water_vnd_per_m3": 25000,
            "water_charge_mode": "per_person_month",
            "internet_vnd_month": 0,
            "service_fee_vnd_month": 0,
            "motorbike_parking_vnd_month": 0,
        },
        "rules": {
            "pets_allowed": False,
            "cooking_allowed": True,
            "shared_with_owner": False,
            "curfew": None,
            "students_welcome": True,
        },
        "parking": {"motorbike": True, "car": False},
        "location": {
            "city": resolved_city,
            "district": str(district).strip(),
            "ward": "",
            "street": "",
            "address_line": "",
            "full_address": f"{str(district).strip()}, {resolved_city}",
            "lat": None,
            "lng": None,
            "distance_to_city_center_km": None,
        },
        "nearby_places": [],
        "landlord": {
            "id": f"LL-{random.randint(10, 99)}",
            "name": landlord_name,
            "phone": landlord_phone,
            "verified": False,
            "response_rate": 0.0,
            "avg_response_minutes": None,
        },
        "rating": 0.0,
        "review_count": 0,
        "images": [],
        "description": description or str(title).strip(),
        "available_from": fields["available_from"],
        "posted_at": today,
        "updated_at": today,
        "viewing_slots": [],
    }

    for key, value in _as_dict(extra).items():
        if key in ("id", "posted_at"):
            continue
        if isinstance(value, dict) and isinstance(listing.get(key), dict):
            listing[key].update(value)
        else:
            listing[key] = value

    data["listings"].append(listing)
    _save(data)
    return f"✅ Đã tạo tin đăng mới với mã '{new_id}'.\n{_summary(listing)}"


@_tool
def add_viewing_slot(listing_id: str, date: str, time: str, duration_minutes: int = 30) -> str:
    """
    [CREATE] Mở thêm một khung giờ cho khách đến xem nhà.

    Args:
        listing_id (str): Mã tin đăng.
        date (str): Ngày xem nhà, định dạng YYYY-MM-DD.
        time (str): Giờ xem nhà, định dạng HH:MM (ví dụ '19:00').
        duration_minutes (int): Thời lượng, mặc định 30 phút.

    Returns:
        str: Xác nhận kèm mã slot vừa tạo.
    """
    listing = _find_listing(listing_id)
    if not listing:
        return f"LỖI: Không tìm thấy tin đăng nào có mã '{listing_id}'."
    _validate_datetime(date, time)

    slots = listing.setdefault("viewing_slots", [])
    if any(s.get("date") == date and s.get("time") == time for s in slots):
        return f"LỖI: Tin {listing['id']} đã có khung giờ {date} {time}."

    slot_id = f"{listing['id']}-S{len(slots) + 1}"
    while any(s.get("slot_id") == slot_id for s in slots):
        slot_id = f"{listing['id']}-S{random.randint(100, 999)}"

    slot = {
        "slot_id": slot_id,
        "date": date,
        "time": time,
        "duration_minutes": int(duration_minutes),
        "status": "available",
        "booked_by": None,
    }
    slots.append(slot)
    listing["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    _save(_load())
    return f"✅ Đã mở khung giờ xem nhà {slot_id} ({date} lúc {time}) cho tin {listing['id']}."


@_tool
def book_viewing(listing_id: str, slot_id: str, customer_name: str, customer_phone: str = "") -> str:
    """
    [CREATE] Đặt lịch đi xem nhà cho khách vào một khung giờ còn trống.

    Args:
        listing_id (str): Mã tin đăng, ví dụ 'DN-HC-002'.
        slot_id (str): Mã khung giờ lấy từ list_viewing_slots, ví dụ 'DN-HC-002-S1'.
        customer_name (str): Tên khách đặt lịch.
        customer_phone (str): Số điện thoại khách (dùng để tra cứu / huỷ lịch).

    Returns:
        str: Xác nhận đặt lịch kèm mã booking, hoặc lý do không đặt được.
    """
    listing = _find_listing(listing_id)
    if not listing:
        return f"LỖI: Không tìm thấy tin đăng nào có mã '{listing_id}'."
    if not str(customer_name).strip():
        raise ValueError("Cần có tên khách hàng để đặt lịch xem nhà.")
    if listing.get("status") == "rented":
        return f"LỖI: Tin {listing['id']} đã cho thuê, không nhận lịch xem nữa."

    key = _norm(slot_id)
    slot = next((s for s in listing.get("viewing_slots", []) if _norm(s.get("slot_id")) == key), None)
    if not slot:
        return (f"LỖI: Tin {listing['id']} không có khung giờ '{slot_id}'. "
                f"Hãy gọi list_viewing_slots['{listing['id']}'] để xem các mã slot hợp lệ.")
    if slot.get("status") != "available":
        return (f"LỖI: Khung giờ {slot['slot_id']} ({slot['date']} {slot['time']}) đã có người đặt. "
                f"Vui lòng chọn khung giờ khác.")

    data = _load()
    booking_no = len(data["bookings"]) + 1
    while any(b.get("booking_id") == f"BK-{booking_no:04d}" for b in data["bookings"]):
        booking_no += 1
    booking_id = f"BK-{booking_no:04d}"
    customer_id = f"KH-{random.randint(1000, 9999)}"

    slot["status"] = "booked"
    slot["booked_by"] = customer_id
    listing["updated_at"] = datetime.now().strftime("%Y-%m-%d")

    booking = {
        "booking_id": booking_id,
        "listing_id": listing["id"],
        "slot_id": slot["slot_id"],
        "date": slot["date"],
        "time": slot["time"],
        "customer_id": customer_id,
        "customer_name": str(customer_name).strip(),
        "customer_phone": str(customer_phone).strip(),
        "status": "confirmed",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    data["bookings"].append(booking)
    _save(data)

    return (
        f"✅ Đặt lịch thành công! Mã booking: {booking_id}\n"
        f"    🏠 {listing['title']} (mã {listing['id']})\n"
        f"    🗓️ {slot['date']} lúc {slot['time']} ({slot['duration_minutes']} phút)\n"
        f"    📍 {listing['location']['full_address']}\n"
        f"    👤 {booking['customer_name']} · ☎ {booking['customer_phone'] or 'chưa cung cấp'}\n"
        f"    🔑 Liên hệ chủ nhà: {listing['landlord']['name']} - {listing['landlord']['phone']}"
    )


# --------------------------------------------------------------------------- #
# ✏️ UPDATE — Cập nhật
# --------------------------------------------------------------------------- #

@_tool
def update_listing(listing_id: str, updates: Union[str, Dict[str, Any], None] = None, **kwargs) -> str:
    """
    [UPDATE] Sửa thông tin một tin đăng đã có.

    Args:
        listing_id (str): Mã tin đăng cần sửa.
        updates (dict|str JSON): Các trường cần đổi,
            ví dụ {"price_vnd_month": 3200000, "status": "pending"}.
            Với trường lồng nhau (utilities, rules, parking, location) chỉ cần truyền
            các khoá con muốn đổi, phần còn lại được giữ nguyên.
        **kwargs: Cách viết ngắn thay cho `updates`, ví dụ update_listing('HN-CG-001', status='rented').

    Returns:
        str: Danh sách các trường đã đổi, hoặc thông báo lỗi.
    """
    listing = _find_listing(listing_id)
    if not listing:
        return f"LỖI: Không tìm thấy tin đăng nào có mã '{listing_id}'."

    payload = _as_dict(updates)
    payload.update(kwargs)
    payload.pop("id", None)
    payload.pop("posted_at", None)
    if not payload:
        return "LỖI: Chưa chỉ định trường nào cần cập nhật."

    unknown = [k for k in payload if k not in listing]
    if unknown:
        raise ValueError(
            f"Không tồn tại trường: {', '.join(unknown)}. "
            f"Các trường hợp lệ: {', '.join(k for k in listing if k != 'id')}."
        )

    clean = _validate_fields(payload)
    changed: List[str] = []
    for key, value in clean.items():
        old = listing.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            merged = dict(old)
            merged.update(value)
            if merged != old:
                listing[key] = merged
                changed.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        elif old != value:
            listing[key] = value
            changed.append(f"{key}: {old} → {value}")

    if not changed:
        return f"ℹ️ Tin {listing['id']} không có gì thay đổi (giá trị mới trùng giá trị cũ)."

    listing["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    _save(_load())
    return f"✅ Đã cập nhật tin {listing['id']}:\n    - " + "\n    - ".join(changed)


@_tool
def cancel_viewing(booking_id: str) -> str:
    """
    [UPDATE] Huỷ một lịch hẹn xem nhà và trả khung giờ về trạng thái còn trống.

    Args:
        booking_id (str): Mã booking nhận được khi đặt lịch, ví dụ 'BK-0001'.

    Returns:
        str: Xác nhận huỷ lịch, hoặc thông báo không tìm thấy booking.
    """
    data = _load()
    key = _norm(booking_id)
    booking = next((b for b in data["bookings"] if _norm(b.get("booking_id")) == key), None)
    if not booking:
        return f"LỖI: Không tìm thấy lịch hẹn nào có mã '{booking_id}'."
    if booking.get("status") == "cancelled":
        return f"ℹ️ Lịch hẹn {booking['booking_id']} đã được huỷ trước đó rồi."

    listing = _find_listing(booking["listing_id"])
    if listing:
        for slot in listing.get("viewing_slots", []):
            if slot.get("slot_id") == booking.get("slot_id"):
                slot["status"] = "available"
                slot["booked_by"] = None
                break
        listing["updated_at"] = datetime.now().strftime("%Y-%m-%d")

    booking["status"] = "cancelled"
    booking["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save(data)
    return (f"✅ Đã huỷ lịch hẹn {booking['booking_id']} "
            f"({booking['date']} lúc {booking['time']}, tin {booking['listing_id']}). "
            f"Khung giờ {booking['slot_id']} đã mở lại cho khách khác.")


# --------------------------------------------------------------------------- #
# 🗑️ DELETE — Xoá
# --------------------------------------------------------------------------- #

@_tool
def delete_listing(listing_id: str) -> str:
    """
    [DELETE] Gỡ một tin đăng khỏi kho dữ liệu (kèm huỷ mọi lịch hẹn liên quan).

    Args:
        listing_id (str): Mã tin đăng cần xoá, ví dụ 'HN-HD-004'.

    Returns:
        str: Xác nhận đã xoá kèm số lịch hẹn bị huỷ theo.
    """
    listing = _find_listing(listing_id)
    if not listing:
        return f"LỖI: Không tìm thấy tin đăng nào có mã '{listing_id}'."

    data = _load()
    data["listings"] = [l for l in data["listings"] if l["id"] != listing["id"]]

    cancelled = 0
    for booking in data["bookings"]:
        if booking.get("listing_id") == listing["id"] and booking.get("status") != "cancelled":
            booking["status"] = "cancelled"
            booking["cancelled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            cancelled += 1

    _save(data)
    return (f"🗑️ Đã xoá tin '{listing['id']}' - {listing['title']}. "
            f"Đã huỷ kèm {cancelled} lịch hẹn. Còn lại {len(data['listings'])} tin trong kho.")


# --------------------------------------------------------------------------- #
# 📇 TOOL REGISTRY & SPECS (để Role 3 / Role 4 nhúng vào System Prompt)
# --------------------------------------------------------------------------- #

AVAILABLE_TOOLS = {
    # READ
    "search_listings": search_listings,
    "get_listing": get_listing,
    "list_viewing_slots": list_viewing_slots,
    "list_bookings": list_bookings,
    # CREATE
    "create_listing": create_listing,
    "add_viewing_slot": add_viewing_slot,
    "book_viewing": book_viewing,
    # UPDATE
    "update_listing": update_listing,
    "cancel_viewing": cancel_viewing,
    # DELETE
    "delete_listing": delete_listing,
}

TOOL_SPECS = [
    {
        "name": "search_listings",
        "args": "city, district, max_price, property_type, min_area, bedrooms, amenities, near…",
        "description": "Tìm danh sách nhà/phòng cho thuê theo khu vực, ngân sách và tiện nghi.",
    },
    {
        "name": "get_listing",
        "args": "listing_id",
        "description": "Xem chi tiết đầy đủ một tin đăng theo mã (giá, nội quy, chi phí, chủ nhà).",
    },
    {
        "name": "list_viewing_slots",
        "args": "listing_id",
        "description": "Xem các khung giờ còn trống để đi xem nhà của một tin đăng.",
    },
    {
        "name": "book_viewing",
        "args": "listing_id, slot_id, customer_name, customer_phone",
        "description": "Đặt lịch đi xem nhà vào một khung giờ còn trống.",
    },
    {
        "name": "cancel_viewing",
        "args": "booking_id",
        "description": "Huỷ lịch hẹn xem nhà đã đặt.",
    },
    {
        "name": "list_bookings",
        "args": "customer_phone, listing_id",
        "description": "Tra cứu các lịch hẹn xem nhà đã đặt.",
    },
    {
        "name": "create_listing",
        "args": "title, city, district, price_vnd_month, area_m2, property_type…",
        "description": "Đăng tin cho thuê mới (dành cho chủ nhà).",
    },
    {
        "name": "add_viewing_slot",
        "args": "listing_id, date, time, duration_minutes",
        "description": "Mở thêm khung giờ xem nhà cho một tin đăng.",
    },
    {
        "name": "update_listing",
        "args": "listing_id, updates (JSON)",
        "description": "Cập nhật thông tin tin đăng (giá, trạng thái, tiện nghi…).",
    },
    {
        "name": "delete_listing",
        "args": "listing_id",
        "description": "Gỡ tin đăng khỏi hệ thống và huỷ các lịch hẹn liên quan.",
    },
]


def get_tool_descriptions() -> str:
    """Sinh đoạn mô tả tool để chèn vào REACT_SYSTEM_PROMPT của Role 3."""
    return "\n".join(
        f"{i}. {spec['name']}[{spec['args']}]: {spec['description']}"
        for i, spec in enumerate(TOOL_SPECS, 1)
    )


if __name__ == "__main__":
    import sys

    if sys.stdout.encoding != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

