"""Outbox and consumer receipt models."""

from __future__ import annotations

import uuid

from django.db import models


class OutboxStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    PROCESSING = "PROCESSING", "Processing"
    PUBLISHED = "PUBLISHED", "Published"
    FAILED = "FAILED", "Failed"


class OutboxEvent(models.Model):
    event_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    event_type = models.CharField(max_length=128)
    aggregate_type = models.CharField(max_length=64)
    aggregate_id = models.UUIDField()
    payload_json = models.JSONField(default=dict)
    occurred_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=OutboxStatus.choices,
        default=OutboxStatus.PENDING,
    )
    attempt_count = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "platform_outbox_event"
        indexes = [
            models.Index(fields=["status", "next_attempt_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}:{self.event_id}"


class ConsumerReceipt(models.Model):
    event = models.ForeignKey(OutboxEvent, on_delete=models.PROTECT, related_name="receipts")
    consumer_code = models.CharField(max_length=64)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "platform_consumer_receipt"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "consumer_code"],
                name="platform_consumer_receipt_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.consumer_code}:{self.event_id}"
