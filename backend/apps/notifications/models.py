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


class NotificationStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    DELIVERED = "DELIVERED", "Delivered"
    FAILED = "FAILED", "Failed"


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications_todo"
        constraints = [
            models.UniqueConstraint(
                fields=["assignee", "dedup_key"],
                condition=models.Q(status=TodoStatus.OPEN),
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
    summary = models.CharField(max_length=512)
    object_type = models.CharField(max_length=64)
    object_id = models.UUIDField()
    dedup_key = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
    )
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
