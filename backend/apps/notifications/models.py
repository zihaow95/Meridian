"""Authoritative todos and notification delivery models."""

from __future__ import annotations

from django.db import models

from apps.identity.models.user import User
from apps.platform.models.base import OrganizationOwnedModel, PublicIdModel


class TodoStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"
    EXPIRED = "EXPIRED", "Expired"


class NotificationCategory(models.TextChoices):
    ACTION_REQUIRED = "ACTION_REQUIRED", "Action required"
    DEADLINE = "DEADLINE", "Deadline"
    BUSINESS_ALERT = "BUSINESS_ALERT", "Business alert"
    PROCESS_RESULT = "PROCESS_RESULT", "Process result"
    SYSTEM_FAILURE = "SYSTEM_FAILURE", "System failure"
    INFORMATION = "INFORMATION", "Information"


class NotificationLevel(models.TextChoices):
    URGENT = "URGENT", "Urgent"
    IMPORTANT = "IMPORTANT", "Important"
    NORMAL = "NORMAL", "Normal"


class NotificationStatus(models.TextChoices):
    """What the recipient has done with the notification.

    Whether a channel accepted it is a different question, answered by
    `Delivery`. Keeping both in one column made a successful send look like a
    read notification.
    """

    UNREAD = "UNREAD", "Unread"
    READ = "READ", "Read"
    CLOSED = "CLOSED", "Closed"


class DeliveryChannel(models.TextChoices):
    IN_APP = "IN_APP", "In app"
    DINGTALK = "DINGTALK", "DingTalk"


class DeliveryStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    SENT = "SENT", "Sent"
    FAILED = "FAILED", "Failed"


class Todo(OrganizationOwnedModel):
    assignee = models.ForeignKey(User, on_delete=models.PROTECT, related_name="todos")
    todo_type = models.CharField(max_length=64)
    source_type = models.CharField(max_length=64)
    source_id = models.UUIDField()
    action_code = models.CharField(max_length=128)
    status = models.CharField(max_length=16, choices=TodoStatus.choices, default=TodoStatus.OPEN)
    due_at = models.DateTimeField(null=True, blank=True)
    dedup_key = models.CharField(max_length=255)
    deep_link = models.CharField(max_length=512)
    title = models.CharField(max_length=255)
    # Nullable sentinel: occupied by the one open todo per assignee and dedup
    # key. MySQL ignores conditional unique constraints.
    open_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_todo"
        constraints = [
            models.UniqueConstraint(
                fields=["assignee", "dedup_key", "open_slot"],
                name="notifications_todo_open_dedup_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["assignee", "status"]),
        ]


class Notification(PublicIdModel):
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT)
    recipient = models.ForeignKey(User, on_delete=models.PROTECT, related_name="notifications")
    template_code = models.CharField(max_length=64)
    # Every service path sets both from the template catalog. Empty is reserved
    # for rows written before classification existed: inventing a category for
    # them would be a guess presented as a fact.
    category = models.CharField(max_length=32, choices=NotificationCategory.choices, blank=True)
    level = models.CharField(max_length=16, choices=NotificationLevel.choices, blank=True)
    summary = models.CharField(max_length=512)
    object_type = models.CharField(max_length=64)
    object_id = models.UUIDField()
    dedup_key = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=NotificationStatus.choices,
        default=NotificationStatus.UNREAD,
    )
    read_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=64, blank=True)
    # The template and policy versions that were in force when this notification
    # was written, so the summary and the channel choice stay explainable after
    # the configuration moves on.
    template_version = models.ForeignKey(
        "configuration.ConfigurationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="notifications",
    )
    policy_version = models.ForeignKey(
        "configuration.ConfigurationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="policy_notifications",
    )
    policy_snapshot = models.JSONField(default=dict, blank=True)
    deep_link = models.CharField(max_length=512)
    todo = models.ForeignKey(
        Todo, on_delete=models.SET_NULL, null=True, blank=True, related_name="notifications"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications_notification"
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "dedup_key"],
                name="notifications_notification_recipient_dedup_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["recipient", "status"]),
            models.Index(fields=["recipient", "category", "level"]),
        ]


class Delivery(PublicIdModel):
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries"
    )
    channel = models.CharField(max_length=16, choices=DeliveryChannel.choices)
    attempt_count = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    error_code = models.CharField(max_length=64, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    external_message_id = models.CharField(max_length=128, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_delivery"
        indexes = [
            models.Index(fields=["channel", "status"]),
        ]
