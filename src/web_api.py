"""FastAPI adapter for the RentMate AgentEngine."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from .app import (
        AgentEngine,
        ConfirmationContext,
        _mask_phone,
        build_default_runtime,
    )
except ImportError:  # Supports `uvicorn web_api:app` from src/.
    from app import AgentEngine, ConfirmationContext, _mask_phone, build_default_runtime


class ConfirmationPayload(BaseModel):
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


def _bookings_from_store(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        data = value.get("data") or {}
        value = data.get("bookings") or value.get("bookings") or []
    return value if isinstance(value, list) else []


def create_app(
    *,
    engine: AgentEngine | None = None,
    store: Any = None,
) -> FastAPI:
    application = FastAPI(
        title="RentMate Agent",
        version="1.0.0",
        description="Chatbot vs ReAct Agent for rental discovery and viewing bookings.",
    )
    runtime = RuntimeHolder(engine, store)

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

        confirmation = (
            ConfirmationContext(**request.confirmation.model_dump())
            if request.confirmation is not None
            else None
        )
        result = current_engine.run_turn(
            request.message,
            mode=request.mode,
            session_id=session_id,
            confirmation=confirmation,
        )
        return {"session_id": session_id, **result.to_dict()}

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
        return {"session_id": session_id, "bookings": _mask_phone(bookings)}

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
            {"session_id": session_id, "bookings": _mask_phone(bookings)}
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

