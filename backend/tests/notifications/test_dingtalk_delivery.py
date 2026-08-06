"""DingTalk delivery is switched off in phase 6, and the refusal is testable.

Previously the only thing standing between the system and a DingTalk send was an
unset `DINGTALK_NOTIFIER`: the gateway was still instantiated and failed with a
generic `RuntimeError` deep inside delivery. That is an accident, not a decision,
and it recorded the refusal as a failed delivery attempt. There is now an
explicit switch, and the failure-recording behaviour is tested with it on.
"""

from __future__ import annotations

import pytest

from apps.notifications.models import DeliveryStatus, TodoStatus
from apps.notifications.services.notifications import (
    DingTalkDeliveryDisabled,
    deliver_notification,
)

pytestmark = pytest.mark.django_db


def test_dingtalk_delivery_is_refused_while_the_channel_is_disabled(
    settings, notification, failing_gateway
) -> None:
    settings.ENABLE_DINGTALK_NOTIFICATIONS = False

    with pytest.raises(DingTalkDeliveryDisabled):
        deliver_notification(notification.id, gateway=failing_gateway)

    assert notification.deliveries.filter(channel="DINGTALK").exists() is False


def test_the_disabled_switch_is_not_bypassed_by_injecting_a_gateway(settings, notification) -> None:
    class RecordingGateway:
        def __init__(self) -> None:
            self.calls = 0

        def send(self, *, recipient_user_id: int, summary: str, deep_link: str) -> str:
            self.calls += 1
            return "external-1"

    settings.ENABLE_DINGTALK_NOTIFICATIONS = False
    gateway = RecordingGateway()

    with pytest.raises(DingTalkDeliveryDisabled):
        deliver_notification(notification.id, gateway=gateway)

    assert gateway.calls == 0


def test_dingtalk_failure_does_not_remove_authoritative_todo(
    settings, todo, notification, failing_gateway
) -> None:
    settings.ENABLE_DINGTALK_NOTIFICATIONS = True

    deliver_notification(notification.id, gateway=failing_gateway)

    todo.refresh_from_db()
    assert todo.status == TodoStatus.OPEN
    delivery = notification.deliveries.get(channel="DINGTALK")
    assert delivery.status == DeliveryStatus.FAILED
    assert delivery.error_code == "RuntimeError"


def test_a_successful_send_does_not_touch_the_recipients_own_lifecycle(
    settings, notification
) -> None:
    class WorkingGateway:
        def send(self, *, recipient_user_id: int, summary: str, deep_link: str) -> str:
            return "external-1"

    settings.ENABLE_DINGTALK_NOTIFICATIONS = True

    deliver_notification(notification.id, gateway=WorkingGateway())

    notification.refresh_from_db()
    assert notification.status == "UNREAD"
    assert notification.deliveries.get(channel="DINGTALK").status == DeliveryStatus.SENT
