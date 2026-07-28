"""Level 3 — thin demo adapter around the shared ReAct orchestration seam."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    try:
        from providers import BaseLLMProvider
    except ImportError:
        from src.providers import BaseLLMProvider


def reactive_agent_step(
    user_goal: str,
    provider: "BaseLLMProvider | None" = None,
    tool_registry: dict[str, Any] | None = None,
) -> Any:
    """Delegate to the shared core without duplicating tools or loop code.

    With no injected dependencies, the standalone demo builds the default
    SQLite runtime so rental Actions have real tools. Tests and other callers
    may inject a provider plus registry through the same compatibility wrapper.
    """

    if provider is None and tool_registry is None:
        try:
            from app import build_default_runtime
        except ImportError:
            import sys
            from pathlib import Path

            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from app import build_default_runtime

        engine, _store = build_default_runtime()
        return engine.run_turn(user_goal, mode="level3")

    if provider is None:
        try:
            from providers import get_llm_provider
        except ImportError:
            import sys
            from pathlib import Path

            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from providers import get_llm_provider

        provider = get_llm_provider()

    # Lazy import prevents app -> ai_levels -> app circular imports.
    try:
        from app import run_react_agent
    except ImportError:
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app import run_react_agent

    if tool_registry is None:
        return run_react_agent(user_goal, provider)
    return run_react_agent(user_goal, provider, tool_registry)


if __name__ == "__main__":
    import json
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    demo_result = reactive_agent_step(
        "Tìm phòng ở Cầu Giấy dưới 5 triệu, có điều hòa và chỗ để xe."
    )
    payload = demo_result.to_dict() if hasattr(demo_result, "to_dict") else demo_result
    print(json.dumps(payload, ensure_ascii=False, indent=2))
