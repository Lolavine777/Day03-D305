"""Portable timezone resolution for RentMate.

Python's :mod:`zoneinfo` reads the operating system timezone database on
Unix-like systems. Windows installations usually need the separate ``tzdata``
package. RentMate declares that dependency, but the fixed-offset fallback keeps
the local app usable if the environment has not been fully provisioned yet.
"""

from __future__ import annotations

from datetime import timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_APP_TIMEZONE = "Asia/Ho_Chi_Minh"
VIETNAM_FIXED_OFFSET = timezone(
    timedelta(hours=7),
    name=DEFAULT_APP_TIMEZONE,
)
_UTC_NAMES = frozenset({"UTC", "ETC/UTC", "GMT"})


def resolve_timezone(
    timezone_name: str | None = None,
    *,
    fallback: tzinfo = VIETNAM_FIXED_OFFSET,
) -> tzinfo:
    """Resolve an IANA timezone and return a safe local fallback if unavailable."""

    name = (timezone_name or DEFAULT_APP_TIMEZONE).strip() or DEFAULT_APP_TIMEZONE
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        if name.upper() in _UTC_NAMES:
            return timezone.utc
        return fallback


VIETNAM_TIMEZONE = resolve_timezone(DEFAULT_APP_TIMEZONE)


__all__ = [
    "DEFAULT_APP_TIMEZONE",
    "VIETNAM_FIXED_OFFSET",
    "VIETNAM_TIMEZONE",
    "resolve_timezone",
]
