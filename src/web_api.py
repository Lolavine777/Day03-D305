"""FastAPI adapter for the RentMate AgentEngine."""

from __future__ import annotations

import os
import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .app import (
        AgentEngine,
        ConfirmationContext,
        build_default_runtime,
    )
    from .privacy import redact_pii
except ImportError:  # Supports `uvicorn web_api:app` from src/.
    from app import AgentEngine, ConfirmationContext, build_default_runtime
    from privacy import redact_pii


class ConfirmationPayload(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    accepted: bool
    property_id: str = Field(min_length=1, max_length=80)
    slot_id: str = Field(min_length=1, max_length=120)
    viewer_name: str = Field(min_length=2, max_length=120)
    viewer_phone: str = Field(min_length=9, max_length=24)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    mode: Literal["auto", "level1", "level2", "level3", "level4"] = "auto"
    confirmation: ConfirmationPayload | None = None


class RuntimeHolder:
    """Lazily build local adapters so imports never create a database."""

    def __init__(self, engine: AgentEngine | None = None, store: Any = None):
        self._engine = engine
        self._store = store
        self._lock = threading.Lock()

    def get(self) -> tuple[AgentEngine, Any]:
        if self._engine is None or self._store is None:
            with self._lock:
                if self._engine is None or self._store is None:
                    self._engine, self._store = build_default_runtime()
        return self._engine, self._store


@dataclass(frozen=True)
class ConfirmationGrant:
    """One short-lived capability binding a session to a returned slot."""

    session_id: str
    property_id: str
    slot_id: str
    expires_at: float


class ConfirmationTokenRegistry:
    """Issue and verify opaque, single-use booking confirmation capabilities."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 900,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.ttl_seconds = max(30, min(int(ttl_seconds), 3600))
        self._clock = clock
        self._grants: dict[str, ConfirmationGrant] = {}
        self._reserved_tokens: set[str] = set()
        self._lock = threading.RLock()

    def issue(self, session_id: str, property_id: str, slot_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        grant = ConfirmationGrant(
            session_id=session_id,
            property_id=property_id.strip().upper(),
            slot_id=slot_id.strip().upper(),
            expires_at=now + self.ttl_seconds,
        )
        with self._lock:
            self._purge_expired(now)
            self._grants[token] = grant
        return token

    def validate(
        self,
        token: str,
        *,
        session_id: str,
        property_id: str,
        slot_id: str,
    ) -> bool:
        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            grant = self._grants.get(token)
            return bool(
                token not in self._reserved_tokens
                and self._matches(
                    grant,
                    session_id=session_id,
                    property_id=property_id,
                    slot_id=slot_id,
                )
            )

    def acquire(
        self,
        token: str,
        *,
        session_id: str,
        property_id: str,
        slot_id: str,
    ) -> bool:
        """Atomically reserve a matching token for one in-flight booking."""

        now = self._clock()
        with self._lock:
            self._purge_expired(now)
            grant = self._grants.get(token)
            matches = self._matches(
                grant,
                session_id=session_id,
                property_id=property_id,
                slot_id=slot_id,
            )
            if not matches or token in self._reserved_tokens:
                return False
            self._reserved_tokens.add(token)
            return True

    def finalize(self, token: str, *, booking_created: bool) -> None:
        """Consume a successful token or release it after a safe failure."""

        with self._lock:
            if booking_created:
                self._grants.pop(token, None)
            self._reserved_tokens.discard(token)

    @staticmethod
    def _matches(
        grant: ConfirmationGrant | None,
        *,
        session_id: str,
        property_id: str,
        slot_id: str,
    ) -> bool:
        return bool(
            grant
            and grant.session_id == session_id
            and grant.property_id == property_id.strip().upper()
            and grant.slot_id == slot_id.strip().upper()
        )

    def _purge_expired(self, now: float) -> None:
        expired_tokens = [
            token
            for token, grant in self._grants.items()
            if grant.expires_at <= now
        ]
        for token in expired_tokens:
            self._grants.pop(token, None)
            self._reserved_tokens.discard(token)


def _bookings_from_store(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        data = value.get("data") or {}
        value = data.get("bookings") or value.get("bookings") or []
    return value if isinstance(value, list) else []


def _confirmation_token_ttl() -> int:
    try:
        return int(os.getenv("CONFIRMATION_TOKEN_TTL_SECONDS", "900"))
    except ValueError:
        return 900


def create_app(
    *,
    engine: AgentEngine | None = None,
    store: Any = None,
    confirmation_tokens: ConfirmationTokenRegistry | None = None,
) -> FastAPI:
    application = FastAPI(
        title="RentMate Agent",
        version="1.0.0",
        description="Chatbot vs ReAct Agent for rental discovery and viewing bookings.",
    )
    runtime = RuntimeHolder(engine, store)
    token_registry = confirmation_tokens or ConfirmationTokenRegistry(
        ttl_seconds=_confirmation_token_ttl()
    )

    frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @application.get("/api/health")
    def health() -> dict[str, str]:
        current_engine, _ = runtime.get()
        return {
            "status": "ok",
            "provider": current_engine.provider.__class__.__name__,
            "database": "ok",
        }

    @application.post("/api/sessions", status_code=201)
    def create_session() -> dict[str, str]:
        current_engine, _ = runtime.get()
        return {"session_id": current_engine.create_session()}

    @application.post("/api/chat")
    def chat(request: ChatRequest) -> dict[str, Any]:
        current_engine, _ = runtime.get()
        session_id = request.session_id
        if not session_id or not current_engine.has_session(session_id):
            session_id = current_engine.create_session()

        confirmation = None
        acquired_token: str | None = None
        if request.confirmation is not None and request.confirmation.accepted:
            payload = request.confirmation
            if not token_registry.acquire(
                payload.token,
                session_id=session_id,
                property_id=payload.property_id,
                slot_id=payload.slot_id,
            ):
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "INVALID_CONFIRMATION_TOKEN",
                        "message": (
                            "Mã xác nhận không hợp lệ hoặc đã hết hạn. "
                            "Hãy tra lịch và chọn lại khung giờ."
                        ),
                    },
                )
            acquired_token = payload.token
            confirmation = ConfirmationContext(
                accepted=True,
                property_id=payload.property_id,
                slot_id=payload.slot_id,
                viewer_name=payload.viewer_name,
                viewer_phone=payload.viewer_phone,
            )
        try:
            result = current_engine.run_turn(
                request.message,
                mode=request.mode,
                session_id=session_id,
                confirmation=confirmation,
            )
        except Exception:
            if acquired_token is not None:
                token_registry.finalize(
                    acquired_token,
                    booking_created=False,
                )
            raise

        if acquired_token is not None:
            token_registry.finalize(
                acquired_token,
                booking_created=result.booking is not None,
            )
        response_payload = result.to_dict()
        issued_slots: list[dict[str, Any]] = []
        for slot in response_payload.get("slots") or []:
            if not isinstance(slot, dict):
                continue
            safe_slot = dict(slot)
            property_id = str(safe_slot.get("property_id", "")).strip()
            slot_id = str(safe_slot.get("slot_id", "")).strip()
            if property_id and slot_id:
                safe_slot["confirmation_token"] = token_registry.issue(
                    session_id,
                    property_id,
                    slot_id,
                )
            issued_slots.append(safe_slot)
        response_payload["slots"] = issued_slots

        return {"session_id": session_id, **response_payload}

    @application.get("/api/bookings")
    def list_bookings(
        session_id: str = Query(min_length=1, max_length=100),
    ) -> dict[str, Any]:
        _, current_store = runtime.get()
        try:
            bookings = _bookings_from_store(
                current_store.list_bookings(session_id)
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Không thể đọc danh sách booking.",
            ) from exc
        return {"session_id": session_id, "bookings": redact_pii(bookings)}

    @application.get("/api/bookings/export")
    def export_bookings(
        session_id: str = Query(min_length=1, max_length=100),
    ) -> JSONResponse:
        _, current_store = runtime.get()
        try:
            exported = current_store.export_bookings(session_id)
            bookings = _bookings_from_store(exported)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Không thể xuất dữ liệu booking.",
            ) from exc
        response = JSONResponse(
            {"session_id": session_id, "bookings": redact_pii(bookings)}
        )
        response.headers["Content-Disposition"] = (
            f'attachment; filename="rentmate-bookings-{session_id[:8]}.json"'
        )
        return response

    frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if frontend_dist.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=str(frontend_dist), html=True),
            name="frontend",
        )

    return application


app = create_app()
