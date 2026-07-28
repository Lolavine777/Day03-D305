"""Central privacy helpers for masking Vietnamese phone numbers."""

from __future__ import annotations

import re
from typing import Any


_PHONE_SEPARATOR = r"[\s./()_\-]*"
_PHONE_PATTERN = re.compile(
    rf"(?<!\d)(?:\(\s*)?"
    rf"(?:(?:\+?84|0084){_PHONE_SEPARATOR}[35789]"
    rf"|0{_PHONE_SEPARATOR}[35789])"
    rf"(?:{_PHONE_SEPARATOR}\d){{8}}"
    rf"(?:\s*\))?"
    rf"(?!\d)"
)
_MASKED_PHONE_PATTERN = re.compile(r"0\d{2,3}\*{3,4}\d{3}")


def _normalize_vietnam_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("0084"):
        digits = f"0{digits[4:]}"
    elif digits.startswith("84"):
        digits = f"0{digits[2:]}"
    if not re.fullmatch(r"0[35789]\d{8}", digits):
        return None
    return digits


def _mask_match(match: re.Match[str]) -> str:
    normalized = _normalize_vietnam_phone(match.group(0))
    if normalized is None:  # Defensive: the regex and normalizer stay fail-closed.
        return "***"
    return f"{normalized[:4]}***{normalized[-3:]}"


def mask_phone_number(value: Any) -> str:
    """Mask phone numbers in one value without exposing their raw digits."""
    text = str(value or "")
    if _MASKED_PHONE_PATTERN.fullmatch(text.strip()):
        return text
    redacted = _PHONE_PATTERN.sub(_mask_match, text)
    return redacted if redacted != text else "***"


def redact_pii(value: Any) -> Any:
    """Return a recursively copied value with phone numbers safely masked."""
    if isinstance(value, dict):
        return {
            key: (
                mask_phone_number(item)
                if "phone" in str(key).casefold()
                else redact_pii(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_pii(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_pii(item) for item in value)
    if isinstance(value, str):
        return _PHONE_PATTERN.sub(_mask_match, value)
    return value


# Compatibility name for call sites that previously used ``_mask_phone``.
mask_phone = redact_pii

__all__ = ["mask_phone", "mask_phone_number", "redact_pii"]
