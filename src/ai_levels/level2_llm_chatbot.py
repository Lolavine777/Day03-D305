"""Level 2 — one LLM call, no tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

try:
    from prompts import CHATBOT_BASELINE_PROMPT
except ImportError:  # Supports running this file directly from the repo root.
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from prompts import CHATBOT_BASELINE_PROMPT

if TYPE_CHECKING:
    try:
        from providers import BaseLLMProvider
    except ImportError:
        from src.providers import BaseLLMProvider


def llm_chatbot(
    user_input: str,
    provider: "BaseLLMProvider | None" = None,
) -> str:
    """Run the baseline protocol: exactly one provider call and zero tools."""

    if provider is None:
        try:
            from providers import get_llm_provider
        except ImportError:
            import sys
            from pathlib import Path

            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            from providers import get_llm_provider

        provider = get_llm_provider()

    return provider.generate(
        user_input,
        system_prompt=CHATBOT_BASELINE_PROMPT,
    )


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    print(llm_chatbot("Tôi cần chú ý gì trong hợp đồng thuê nhà?"))
