"""Recipient-owned lifecycle for in-app notifications.

Channel outcomes stay on `Delivery`. This module answers only what the recipient
has done with the notification, and it does it with conditional updates so a
concurrent second click cannot overwrite the first timestamp or reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.notifications.models import Notification, NotificationStatus
from apps.platform.api.errors import PermissionDeniedError, ResourceNotFoundError
from apps.platform.application.command import CommandContext


@dataclass(frozen=True)
class MarkNotificationRead:
    context: CommandContext
    notification_public_id: UUID

    def execute(self) -> Notification:
        actor = self.context.actor
        with transaction.atomic():
            notification = (
                Notification.objects.select_for_update()
                .filter(
                    public_id=self.notification_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if notification is None or notification.recipient_id != actor.id:
                # Same surface either way: the actor must not learn the row exists.
                raise (
                    PermissionDeniedError() if notification is not None else ResourceNotFoundError()
                )

            if notification.status != NotificationStatus.UNREAD:
                return notification

            now = self.context.occurred_at or timezone.now()
            updated = Notification.objects.filter(
                pk=notification.pk,
                status=NotificationStatus.UNREAD,
            ).update(status=NotificationStatus.READ, read_at=now)
            notification.refresh_from_db()
            if updated:
                append_event(
                    AuditRecord(
                        actor=actor,
                        action_code="notification.message.mark_read",
                        resource_type="notification.message",
                        resource_public_id=notification.public_id,
                        result=AuditResult.SUCCESS,
                        trace_id=self.context.trace_id,
                        occurred_at=now,
                        acting_roles_snapshot=acting_roles_snapshot(actor),
                        after_summary={"status": notification.status},
                    )
                )
            return notification


@dataclass(frozen=True)
class CloseNotification:
    context: CommandContext
    notification_public_id: UUID
    close_reason: str = ""

    def execute(self) -> Notification:
        actor = self.context.actor
        with transaction.atomic():
            notification = (
                Notification.objects.select_for_update()
                .filter(
                    public_id=self.notification_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if notification is None or notification.recipient_id != actor.id:
                raise (
                    PermissionDeniedError() if notification is not None else ResourceNotFoundError()
                )

            if notification.status == NotificationStatus.CLOSED:
                return notification

            now = self.context.occurred_at or timezone.now()
            updated = (
                Notification.objects.filter(pk=notification.pk)
                .exclude(status=NotificationStatus.CLOSED)
                .update(
                    status=NotificationStatus.CLOSED,
                    closed_at=now,
                    close_reason=self.close_reason,
                )
            )
            notification.refresh_from_db()
            if updated:
                append_event(
                    AuditRecord(
                        actor=actor,
                        action_code="notification.message.close",
                        resource_type="notification.message",
                        resource_public_id=notification.public_id,
                        result=AuditResult.SUCCESS,
                        trace_id=self.context.trace_id,
                        occurred_at=now,
                        acting_roles_snapshot=acting_roles_snapshot(actor),
                        after_summary={
                            "status": notification.status,
                            "close_reason": notification.close_reason,
                        },
                    )
                )
            return notification


@dataclass(frozen=True)
class SynchronizeNotificationForSource:
    """Close open notifications that point at a settled domain source.

    A repeated sync must not reopen a closed fact or overwrite the first close.
    """

    organization_id: int
    source_type: str
    source_id: UUID
    close_reason: str = "SOURCE_SETTLED"

    def execute(self) -> int:
        now = timezone.now()
        return (
            Notification.objects.filter(
                organization_id=self.organization_id,
                object_type=self.source_type,
                object_id=self.source_id,
            )
            .filter(Q(status=NotificationStatus.UNREAD) | Q(status=NotificationStatus.READ))
            .update(
                status=NotificationStatus.CLOSED,
                closed_at=now,
                close_reason=self.close_reason,
            )
        )
