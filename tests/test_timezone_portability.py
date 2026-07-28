from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_tzdata_is_declared_as_a_runtime_dependency() -> None:
    requirements = {
        line.strip().casefold()
        for line in (PROJECT_ROOT / "requirements.txt").read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "tzdata" in requirements


def test_api_session_starts_when_system_timezone_database_is_missing() -> None:
    script = textwrap.dedent(
        """
        import os
        import re
        import tempfile
        import zoneinfo

        from fastapi.testclient import TestClient


        def missing_timezone(key):
            raise zoneinfo.ZoneInfoNotFoundError(
                f"No time zone found with key {key}"
            )


        zoneinfo.ZoneInfo = missing_timezone

        with tempfile.TemporaryDirectory() as temporary_directory:
            os.environ["DB_PATH"] = os.path.join(
                temporary_directory,
                "rentmate.db",
            )
            os.environ["LLM_PROVIDER"] = "openai"
            os.environ["OPENAI_API_KEY"] = "test-only-api-key"

            from src.app import build_default_runtime
            from src.web_api import create_app

            engine, store = build_default_runtime()
            try:
                with TestClient(create_app(engine=engine, store=store)) as client:
                    response = client.post("/api/sessions")
            finally:
                store.close()

            assert response.status_code == 201, response.text

            from src.providers import _next_saturday

            assert re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}", _next_saturday())
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
