"""SQLite persistence for the RentMate rental inventory and viewing bookings."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from .privacy import mask_phone_number
except ImportError:  # Supports ``python src/app.py``.
    from privacy import mask_phone_number


DEFAULT_APP_TIMEZONE = "Asia/Ho_Chi_Minh"
APP_TIMEZONE = ZoneInfo(DEFAULT_APP_TIMEZONE)
DEFAULT_SLOT_TIMES = ("09:00", "14:00", "18:30")


def _configured_timezone() -> ZoneInfo:
    timezone_name = os.getenv("APP_TIMEZONE", "").strip() or DEFAULT_APP_TIMEZONE
    try:
        return ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return APP_TIMEZONE


class RentalStoreError(RuntimeError):
    """Domain failure raised by atomic store operations."""

    def __init__(
        self,
        code: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class RentalStore:
    """Persistent store used by rental tools.

    ``db_path=":memory:"`` provides the lightweight in-memory adapter used by
    tests. No database is opened until :meth:`initialize` or another public
    data method is called.
    """

    def __init__(
        self,
        db_path: str | Path = "rentmate.db",
        inventory_path: str | Path | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self.inventory_path = (
            Path(inventory_path)
            if inventory_path is not None
            else Path(__file__).resolve().parents[1] / "config" / "rental_inventory.json"
        )
        self._timezone = _configured_timezone()
        self._now_factory = now_factory or (lambda: datetime.now(self._timezone))
        self._connection_instance: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def initialize(self) -> None:
        """Create the schema, seed inventory, and seed 14 upcoming local days."""
        with self._lock:
            connection = self._connection()
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS properties (
                    property_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    city TEXT NOT NULL,
                    district TEXT NOT NULL,
                    ward TEXT NOT NULL,
                    address TEXT NOT NULL,
                    price_vnd INTEGER NOT NULL,
                    property_type TEXT NOT NULL,
                    area_m2 REAL NOT NULL,
                    amenities_json TEXT NOT NULL,
                    deposit_months REAL NOT NULL,
                    available INTEGER NOT NULL,
                    description TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS viewing_slots (
                    slot_id TEXT PRIMARY KEY,
                    property_id TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    UNIQUE(property_id, starts_at),
                    FOREIGN KEY(property_id) REFERENCES properties(property_id)
                );

                CREATE TABLE IF NOT EXISTS bookings (
                    booking_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    property_id TEXT NOT NULL,
                    slot_id TEXT NOT NULL UNIQUE,
                    viewer_name TEXT NOT NULL,
                    viewer_phone TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(property_id) REFERENCES properties(property_id),
                    FOREIGN KEY(slot_id) REFERENCES viewing_slots(slot_id)
                );

                CREATE INDEX IF NOT EXISTS idx_slots_property_start
                    ON viewing_slots(property_id, starts_at);
                CREATE INDEX IF NOT EXISTS idx_bookings_session
                    ON bookings(session_id, created_at);
                """
            )
            self._seed_inventory(connection)
            self._seed_viewing_slots(connection)
            connection.commit()

    def list_properties(self) -> list[dict[str, Any]]:
        """Return the seeded inventory in stable property-id order."""
        with self._lock:
            rows = self._connection().execute(
                "SELECT * FROM properties ORDER BY property_id"
            ).fetchall()
        return [self._property_from_row(row) for row in rows]

    def get_property(self, property_id: str) -> dict[str, Any] | None:
        """Return one property or ``None`` when the id is not in inventory."""
        with self._lock:
            row = self._connection().execute(
                "SELECT * FROM properties WHERE property_id = ?",
                (property_id,),
            ).fetchone()
        return self._property_from_row(row) if row is not None else None

    def list_available_slots(
        self,
        property_id: str,
        date_text: str | None = None,
    ) -> list[dict[str, str]]:
        """Return unbooked slots for a property, optionally on one local date."""
        sql = """
            SELECT slot.slot_id, slot.property_id, slot.starts_at
            FROM viewing_slots AS slot
            LEFT JOIN bookings AS booking ON booking.slot_id = slot.slot_id
            WHERE slot.property_id = ? AND booking.slot_id IS NULL
        """
        parameters: list[Any] = [property_id, self._local_now().isoformat()]
        sql += " AND slot.starts_at > ?"
        if date_text is not None:
            sql += " AND slot.starts_at LIKE ?"
            parameters.append(f"{date_text}%")
        sql += " ORDER BY slot.starts_at"
        with self._lock:
            rows = self._connection().execute(sql, parameters).fetchall()
        return [
            {
                "slot_id": row["slot_id"],
                "property_id": row["property_id"],
                "starts_at": row["starts_at"],
            }
            for row in rows
        ]

    def local_today(self) -> date:
        """Return today's date in the configured Vietnam timezone."""
        return self._local_now().date()

    def create_booking(
        self,
        *,
        session_id: str,
        property_id: str,
        slot_id: str,
        viewer_name: str,
        viewer_phone: str,
    ) -> dict[str, Any]:
        """Atomically reserve one slot and return the persisted booking."""
        with self._lock:
            connection = self._connection()
            connection.execute("BEGIN IMMEDIATE")
            try:
                property_row = connection.execute(
                    """
                    SELECT property_id, title, available
                    FROM properties
                    WHERE property_id = ?
                    """,
                    (property_id,),
                ).fetchone()
                if property_row is None:
                    raise RentalStoreError(
                        "NOT_FOUND",
                        f"Không tìm thấy căn có mã {property_id}.",
                        {"property_id": property_id},
                    )
                if not bool(property_row["available"]):
                    raise RentalStoreError(
                        "SLOT_UNAVAILABLE",
                        f"Căn {property_id} hiện không còn nhận lịch xem.",
                        {"property_id": property_id},
                    )

                slot_row = connection.execute(
                    """
                    SELECT slot_id, property_id, starts_at
                    FROM viewing_slots
                    WHERE slot_id = ? AND property_id = ?
                    """,
                    (slot_id, property_id),
                ).fetchone()
                if slot_row is None:
                    raise RentalStoreError(
                        "SLOT_UNAVAILABLE",
                        "Khung giờ không tồn tại hoặc không thuộc căn đã chọn.",
                        {"property_id": property_id, "slot_id": slot_id},
                    )

                booking_id = f"BK-{uuid.uuid4().hex[:12].upper()}"
                created_at = self._local_now().isoformat()
                try:
                    connection.execute(
                        """
                        INSERT INTO bookings (
                            booking_id, session_id, property_id, slot_id,
                            viewer_name, viewer_phone, status, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?)
                        """,
                        (
                            booking_id,
                            session_id,
                            property_id,
                            slot_id,
                            viewer_name,
                            viewer_phone,
                            created_at,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise RentalStoreError(
                        "CONFLICT",
                        "Khung giờ vừa được người khác đặt. Vui lòng chọn lịch khác.",
                        {"property_id": property_id, "slot_id": slot_id},
                    ) from exc

                connection.commit()
                return {
                    "booking_id": booking_id,
                    "session_id": session_id,
                    "property_id": property_id,
                    "property_title": property_row["title"],
                    "slot_id": slot_id,
                    "starts_at": slot_row["starts_at"],
                    "viewer_name": viewer_name,
                    "viewer_phone": viewer_phone,
                    "status": "confirmed",
                    "created_at": created_at,
                }
            except Exception:
                connection.rollback()
                raise

    def list_bookings(self, session_id: str) -> list[dict[str, Any]]:
        """Return one session's bookings with phone numbers masked."""
        if not isinstance(session_id, str) or not session_id.strip():
            return []
        with self._lock:
            rows = self._connection().execute(
                """
                SELECT
                    booking.booking_id,
                    booking.session_id,
                    booking.property_id,
                    property.title AS property_title,
                    property.address AS property_address,
                    booking.slot_id,
                    slot.starts_at,
                    booking.viewer_name,
                    booking.viewer_phone,
                    booking.status,
                    booking.created_at
                FROM bookings AS booking
                JOIN properties AS property
                    ON property.property_id = booking.property_id
                JOIN viewing_slots AS slot
                    ON slot.slot_id = booking.slot_id
                WHERE booking.session_id = ?
                ORDER BY booking.created_at, booking.booking_id
                """,
                (session_id.strip(),),
            ).fetchall()
        return [
            {
                "booking_id": row["booking_id"],
                "session_id": row["session_id"],
                "property_id": row["property_id"],
                "property_title": row["property_title"],
                "property_address": row["property_address"],
                "slot_id": row["slot_id"],
                "starts_at": row["starts_at"],
                "viewer_name": row["viewer_name"],
                "viewer_phone": mask_phone_number(row["viewer_phone"]),
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def export_bookings(self, session_id: str) -> dict[str, Any]:
        """Return a versioned JSON-ready export with PII already masked."""
        normalized_session_id = (
            session_id.strip() if isinstance(session_id, str) else ""
        )
        bookings = self.list_bookings(normalized_session_id)
        return {
            "schema_version": "1.0",
            "session_id": normalized_session_id,
            "exported_at": self._local_now().isoformat(),
            "total": len(bookings),
            "bookings": bookings,
        }

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        with self._lock:
            if self._connection_instance is not None:
                self._connection_instance.close()
                self._connection_instance = None

    def _connection(self) -> sqlite3.Connection:
        if self._connection_instance is None:
            if self.db_path != ":memory:":
                Path(self.db_path).expanduser().resolve().parent.mkdir(
                    parents=True, exist_ok=True
                )
            connection = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            self._connection_instance = connection
        return self._connection_instance

    def _seed_inventory(self, connection: sqlite3.Connection) -> None:
        with self.inventory_path.open("r", encoding="utf-8") as inventory_file:
            payload = json.load(inventory_file)
        properties = payload.get("properties")
        if not isinstance(properties, list):
            raise ValueError("rental_inventory.json must contain a properties list")

        for item in properties:
            connection.execute(
                """
                INSERT INTO properties (
                    property_id, title, city, district, ward, address,
                    price_vnd, property_type, area_m2, amenities_json,
                    deposit_months, available, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(property_id) DO UPDATE SET
                    title=excluded.title,
                    city=excluded.city,
                    district=excluded.district,
                    ward=excluded.ward,
                    address=excluded.address,
                    price_vnd=excluded.price_vnd,
                    property_type=excluded.property_type,
                    area_m2=excluded.area_m2,
                    amenities_json=excluded.amenities_json,
                    deposit_months=excluded.deposit_months,
                    available=excluded.available,
                    description=excluded.description
                """,
                (
                    item["property_id"],
                    item["title"],
                    item["city"],
                    item["district"],
                    item["ward"],
                    item["address"],
                    item["price_vnd"],
                    item["property_type"],
                    item["area_m2"],
                    json.dumps(item["amenities"], ensure_ascii=False),
                    item["deposit_months"],
                    int(bool(item["available"])),
                    item["description"],
                ),
            )

    def _seed_viewing_slots(self, connection: sqlite3.Connection) -> None:
        local_now = self._local_now()
        available_ids = [
            row["property_id"]
            for row in connection.execute(
                "SELECT property_id FROM properties WHERE available = 1"
            ).fetchall()
        ]
        for day_offset in range(1, 15):
            slot_date = (local_now + timedelta(days=day_offset)).date()
            for time_text in DEFAULT_SLOT_TIMES:
                starts_at = datetime.fromisoformat(
                    f"{slot_date.isoformat()}T{time_text}:00"
                ).replace(tzinfo=self._timezone)
                for property_id in available_ids:
                    slot_id = (
                        f"{property_id}-{slot_date.strftime('%Y%m%d')}-"
                        f"{time_text.replace(':', '')}"
                    )
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO viewing_slots (
                            slot_id, property_id, starts_at
                        ) VALUES (?, ?, ?)
                        """,
                        (slot_id, property_id, starts_at.isoformat()),
                    )

    def _local_now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None:
            return value.replace(tzinfo=self._timezone)
        return value.astimezone(self._timezone)

    @staticmethod
    def _property_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "property_id": row["property_id"],
            "title": row["title"],
            "city": row["city"],
            "district": row["district"],
            "ward": row["ward"],
            "address": row["address"],
            "price_vnd": row["price_vnd"],
            "property_type": row["property_type"],
            "area_m2": row["area_m2"],
            "amenities": json.loads(row["amenities_json"]),
            "deposit_months": row["deposit_months"],
            "available": bool(row["available"]),
            "description": row["description"],
        }

# Backward-compatible implementation name used by the composition root.
SQLiteRentalStore = RentalStore
