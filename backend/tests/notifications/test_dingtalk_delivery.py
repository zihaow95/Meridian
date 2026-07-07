"""DingTalk delivery failure handling."""

from __future__ import annotations

import pytest

from apps.notifications.models import DeliveryStatus, TodoStatus
from apps.notifications.services.notifications import deliver_notification


@pytest.mark.django_db
def test_dingtalk_failure_does_not_remove_authoritative_todo(
    todo, notification, failing_gateway
) -> None:
    deliver_notification(notification.id, gateway=failing_gateway)
    todo.refresh_from_db()
    assert todo.status == TodoStatus.OPEN
    delivery = notification.deliveries.get(channel="DINGTALK")
    assert delivery.status == DeliveryStatus.FAILED
    assert delivery.error_code == "RuntimeError"
