"""Parse and humanize human-friendly durations like ``30d``, ``12h``, ``45m``.

Supported units: ``s`` (seconds), ``m`` (minutes), ``h`` (hours), ``d`` (days),
``w`` (weeks). A bare number is interpreted as seconds. Multiple components may
be combined, e.g. ``1d12h``.
"""

from __future__ import annotations

import re

_UNIT_SECONDS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86_400,
    "w": 604_800,
}

# One or more "<number><unit>" pairs, or a bare integer (seconds).
_COMPONENT_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
_BARE_INT_RE = re.compile(r"^\s*\d+\s*$")


class DurationError(ValueError):
    """Raised when a duration string cannot be parsed."""


def parse_duration(text: str) -> int:
    """Parse a duration string into a positive number of seconds.

    Raises :class:`DurationError` on empty, malformed, or non-positive input.
    """
    if text is None:
        raise DurationError("Duration is required.")
    raw = text.strip().lower()
    if not raw:
        raise DurationError("Duration is required.")

    if _BARE_INT_RE.match(raw):
        seconds = int(raw)
    else:
        matches = list(_COMPONENT_RE.finditer(raw))
        # Reject input that has leftover characters outside recognized components.
        consumed = "".join(m.group(0).replace(" ", "") for m in matches)
        if not matches or consumed != raw.replace(" ", ""):
            raise DurationError(
                f"Could not parse duration {text!r}. "
                "Use forms like '30d', '12h', '45m', or '1d12h'."
            )
        seconds = sum(int(num) * _UNIT_SECONDS[unit] for num, unit in
                      ((m.group(1), m.group(2)) for m in matches))

    if seconds <= 0:
        raise DurationError("Duration must be greater than zero.")
    return seconds


def humanize_duration(seconds: int) -> str:
    """Render a number of seconds as a compact human string, e.g. ``1d 12h``."""
    if seconds <= 0:
        return "0s"
    parts: list[str] = []
    remaining = seconds
    for unit in ("w", "d", "h", "m", "s"):
        size = _UNIT_SECONDS[unit]
        if remaining >= size:
            value, remaining = divmod(remaining, size)
            parts.append(f"{value}{unit}")
    return " ".join(parts)
