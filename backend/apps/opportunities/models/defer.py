"""Deferred pool records and quarterly-review outcomes (append-only)."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class DeferStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    CLOSED = "CLOSED", "Closed"


class QuarterlyAction(models.TextChoices):
    CONTINUE_DEFERRED = "CONTINUE_DEFERRED", "Continue deferred"
    RESTART_REVIEW = "RESTART_REVIEW", "Restart review"
    CONVERT_TO_PASS = "CONVERT_TO_PASS", "Convert to pass"
    UPDATE_TRIGGER = "UPDATE_TRIGGER", "Update trigger"


class DeferRecord(OrganizationOwnedModel):
    subject_type = models.CharField(max_length=32)
    subject_public_id = models.UUIDField()
    stage_code = models.CharField(max_length=32)
    last_conclusion = models.CharField(max_length=32, blank=True, default="")
    defer_reason = models.TextField(blank=True, default="")
    restart_trigger = models.TextField(blank=True, default="")
    responsible_user = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deferred_items",
    )
    next_review_quarter = models.CharField(max_length=8, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=DeferStatus.choices,
        default=DeferStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "opportunities_defer_record"
        indexes = [
            models.Index(fields=["subject_type", "subject_public_id", "status"]),
            models.Index(fields=["organization", "status", "next_review_quarter"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject_type}:{self.subject_public_id}:{self.status}"


class DeferReviewEntry(OrganizationOwnedModel):
    defer_record = models.ForeignKey(
        DeferRecord,
        on_delete=models.PROTECT,
        related_name="review_entries",
    )
    action = models.CharField(max_length=32, choices=QuarterlyAction.choices)
    note = models.TextField(blank=True, default="")
    new_restart_trigger = models.TextField(blank=True, default="")
    new_next_review_quarter = models.CharField(max_length=8, blank=True, default="")
    resulting_cycle = models.ForeignKey(
        "stage_gates.StageGateInstance",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="defer_review_entries",
    )
    reviewed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="defer_reviews",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "opportunities_defer_review_entry"
        indexes = [
            models.Index(fields=["defer_record", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.defer_record_id}:{self.action}"
