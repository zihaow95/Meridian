"""Transactional command context shared by critical write services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.utils import timezone

from apps.platform.request_context import get_or_create_trace_id

if TYPE_CHECKING:
    from apps.identity.models.user import User


@dataclass(frozen=True)
class CommandContext:
    actor: User
    trace_id: str
    occurred_at: datetime

    @classmethod
    def for_actor(cls, actor: User, *, trace_id: str | None = None) -> CommandContext:
        return cls(
            actor=actor,
            trace_id=trace_id or get_or_create_trace_id(),
            occurred_at=timezone.now(),
        )
