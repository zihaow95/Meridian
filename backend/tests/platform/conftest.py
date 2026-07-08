"""Platform outbox test fixtures."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.platform.outbox.models import OutboxEvent
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@pytest.fixture
def outbox_event(db: None) -> OutboxEvent:
    return register_outbox_event(
        OutboxMessage(
            event_type="identity.user_status_changed",
            aggregate_type="identity.user",
            aggregate_id=uuid4(),
            payload={"status": "DISABLED"},
            occurred_at=timezone.now(),
        )
    )
