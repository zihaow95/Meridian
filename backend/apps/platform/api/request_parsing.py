"""Strict parsing helpers for HTTP request payloads."""

from __future__ import annotations

from typing import Any

from apps.platform.api.errors import ValidationFailedError


def parse_request_bool(value: Any, *, field: str) -> bool:
    """Parse a boolean without treating non-empty strings as true.

    Python's ``bool("false")`` is ``True``. Request bodies from JSON usually
    arrive as real booleans, but form-encoded or loosely typed clients may send
    the strings ``"true"`` / ``"false"``. Those must not flip into the wrong
    branch of a state machine.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise ValidationFailedError(message=f"{field} must be a boolean.")
