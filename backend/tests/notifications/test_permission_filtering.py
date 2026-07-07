"""Notification permission filtering."""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.authorization.context import AuthorizationDecision
from apps.identity.models.user import User
from apps.notifications.models import Notification
from apps.notifications.services.notifications import CreateInAppNotification


@pytest.mark.django_db
def test_unauthorized_recipient_does_not_receive_notification(
    active_user: User, monkeypatch
) -> None:
    monkeypatch.setattr(
        "apps.notifications.services.notifications.authorize",
        lambda *args, **kwargs: AuthorizationDecision(allowed=False, reason_code="DENIED"),
    )
    result = CreateInAppNotification(
        recipient=active_user,
        template_code="secret",
        summary="Should not persist",
        object_type="identity.user",
        object_id=uuid4(),
        dedup_key="secret:1",
        deep_link="/secret",
    ).execute()
    assert result is None
    assert Notification.objects.count() == 0
