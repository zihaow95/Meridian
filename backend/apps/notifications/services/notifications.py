"""In-app notifications and external delivery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from django.conf import settings
from django.utils import timezone

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.policies.engine import authorize
from apps.identity.models.user import User
from apps.notifications.channels.dingtalk import DingTalkNotificationGateway
from apps.notifications.models import (
    Delivery,
    DeliveryChannel,
    DeliveryStatus,
    Notification,
    NotificationStatus,
    Todo,
)
from apps.notifications.services.policies import resolve_notification


class DingTalkDeliveryDisabled(Exception):
    """Phase 6 keeps DingTalk off; delivery must refuse before a gateway is touched."""


class NotificationGateway(Protocol):
    def send(self, *, recipient_user_id: int, summary: str, deep_link: str) -> str: ...


@dataclass(frozen=True)
class CreateInAppNotification:
    recipient: User
    template_code: str
    object_type: str
    object_id: UUID
    dedup_key: str
    deep_link: str
    variables: dict[str, Any] | None = None
    # Kept only so older call sites that still pass a pre-rendered summary fail
    # closed: a summary that never went through a template is how object bodies
    # leak. Prefer `variables`.
    summary: str | None = None
    todo: Todo | None = None
    action_code: str = "notification.read"

    def execute(self) -> Notification | None:
        decision = authorize(
            _subject_for(self.recipient),
            action=self.action_code,
            resource=ResourceDescriptor(
                resource_type=self.object_type,
                public_id=self.object_id,
                organization_id=self.recipient.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            return None

        if self.variables is None:
            raise ValueError(
                "CreateInAppNotification requires template variables; a raw "
                "summary is no longer accepted."
            )

        resolved = resolve_notification(
            organization=self.recipient.organization,
            template_code=self.template_code,
            variables=self.variables,
        )

        notification, _ = Notification.objects.get_or_create(
            recipient=self.recipient,
            dedup_key=self.dedup_key,
            defaults={
                "organization": self.recipient.organization,
                "template_code": resolved.template_code,
                "category": resolved.category,
                "level": resolved.level,
                "summary": resolved.summary,
                "object_type": self.object_type,
                "object_id": self.object_id,
                "status": NotificationStatus.UNREAD,
                "template_version_id": resolved.template_version_id,
                "policy_version_id": resolved.policy_version_id,
                "policy_snapshot": resolved.policy_snapshot,
                "deep_link": self.deep_link,
                "todo": self.todo,
            },
        )
        # Phase 6 only opens the in-app channel, even when a policy lists more.
        # DingTalk stays behind ENABLE_DINGTALK_NOTIFICATIONS and DeliverNotification.
        if DeliveryChannel.IN_APP in resolved.channels:
            Delivery.objects.get_or_create(
                notification=notification,
                channel=DeliveryChannel.IN_APP,
                defaults={"status": DeliveryStatus.SENT},
            )
        return notification


@dataclass(frozen=True)
class DeliverNotification:
    notification_id: int
    gateway: NotificationGateway | None = None

    def execute(self) -> Delivery:
        if not getattr(settings, "ENABLE_DINGTALK_NOTIFICATIONS", False):
            raise DingTalkDeliveryDisabled(
                "DingTalk notification delivery is disabled for this environment."
            )

        gateway = self.gateway or DingTalkNotificationGateway()
        notification = Notification.objects.select_related("recipient").get(pk=self.notification_id)
        delivery, _ = Delivery.objects.get_or_create(
            notification=notification,
            channel=DeliveryChannel.DINGTALK,
            defaults={"status": DeliveryStatus.PENDING},
        )
        delivery.attempt_count += 1
        try:
            external_id = gateway.send(
                recipient_user_id=notification.recipient_id,
                summary=notification.summary,
                deep_link=notification.deep_link,
            )
        except Exception as exc:  # noqa: BLE001 - record sanitized failure
            delivery.status = DeliveryStatus.FAILED
            delivery.error_code = type(exc).__name__
            delivery.save(update_fields=["attempt_count", "status", "error_code", "updated_at"])
            return delivery

        delivery.status = DeliveryStatus.SENT
        delivery.external_message_id = external_id
        delivery.save(
            update_fields=["attempt_count", "status", "external_message_id", "updated_at"]
        )
        # A successful send says nothing about whether the recipient read it, so
        # the notification's own lifecycle is left alone.
        return delivery


def deliver_notification(
    notification_id: int,
    *,
    gateway: NotificationGateway | None = None,
) -> Delivery:
    return DeliverNotification(notification_id=notification_id, gateway=gateway).execute()


def _subject_for(user: User) -> AuthorizationSubject:
    from django.db import models

    from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment

    now = timezone.now()
    role_codes = frozenset(
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=now,
        )
        .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gt=now))
        .values_list("role__role_code", flat=True)
    )
    return AuthorizationSubject(user=user, role_codes=role_codes)
