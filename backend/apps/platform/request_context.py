"""Per-request context: trace identifier generation and access."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)


def generate_trace_id() -> str:
    return str(uuid.uuid4())


def set_trace_id(trace_id: str) -> None:
    _trace_id.set(trace_id)


def get_trace_id() -> str | None:
    return _trace_id.get()


def get_or_create_trace_id() -> str:
    current = get_trace_id()
    if current is not None:
        return current
    trace_id = generate_trace_id()
    set_trace_id(trace_id)
    return trace_id
