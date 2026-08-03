"""Pilot batches, participant snapshots, and software-feedback facts.

Software feedback is not an operating issue. This domain stays small and only
stores what Phase 6 needs to prove a governed create→assign→retest→close loop.
"""

from __future__ import annotations

from typing import Any

from django.db import models

from apps.identity.models.user import User
from apps.platform.models.base import OrganizationOwnedModel


class PilotBatchStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    OPEN = "OPEN", "Open"
    COMPLETED = "COMPLETED", "Completed"


class PilotBatchPurpose(models.TextChoices):
    # Phase 6 may only exercise internal acceptance data.
    INTERNAL_ACCEPTANCE = "INTERNAL_ACCEPTANCE", "Internal acceptance"
    BUSINESS_PILOT = "BUSINESS_PILOT", "Business pilot"


class PilotFeedbackSeverity(models.TextChoices):
    P0 = "P0", "P0"
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"


class PilotFeedbackStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    TRIAGED = "TRIAGED", "Triaged"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    READY_FOR_RETEST = "READY_FOR_RETEST", "Ready for retest"
    CLOSED = "CLOSED", "Closed"
    REJECTED = "REJECTED", "Rejected"


class PilotBatch(OrganizationOwnedModel):
    name = models.CharField(max_length=128)
    purpose = models.CharField(
        max_length=32,
        choices=PilotBatchPurpose.choices,
        default=PilotBatchPurpose.INTERNAL_ACCEPTANCE,
    )
    status = models.CharField(
        max_length=16,
        choices=PilotBatchStatus.choices,
        default=PilotBatchStatus.DRAFT,
    )
    # Editable defaults; never hard-code the business "8 people / 2 weeks" rule.
    planned_participant_count = models.PositiveSmallIntegerField(default=8)
    planned_duration_days = models.PositiveSmallIntegerField(default=14)
    # Frozen when the batch leaves DRAFT so later config edits do not rewrite history.
    config_snapshot = models.JSONField(default=dict, blank=True)
    data_scope_note = models.CharField(max_length=512, blank=True)
    feedback_owner_note = models.CharField(max_length=255, blank=True)
    known_limits_note = models.TextField(blank=True)
    stop_conditions_note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="created_pilot_batches"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    version_no = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pilot_batch"
        indexes = [
            models.Index(fields=["organization", "status"]),
        ]


class PilotParticipant(OrganizationOwnedModel):
    batch = models.ForeignKey(PilotBatch, on_delete=models.PROTECT, related_name="participants")
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="pilot_participations")
    display_name_snapshot = models.CharField(max_length=128)
    employee_no_snapshot = models.CharField(max_length=64, blank=True)
    department_snapshot = models.CharField(max_length=128, blank=True)
    role_codes_snapshot = models.JSONField(default=list, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pilot_participant"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "user"],
                name="pilot_participant_batch_user_uniq",
            )
        ]


class PilotFeedback(OrganizationOwnedModel):
    batch = models.ForeignKey(PilotBatch, on_delete=models.PROTECT, related_name="feedback_items")
    reporter = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name="reported_pilot_feedback"
    )
    assignee = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assigned_pilot_feedback",
    )
    title = models.CharField(max_length=255)
    # Reproduction only — never copy sensitive product body into this summary.
    reproduction_summary = models.CharField(max_length=1024)
    severity = models.CharField(
        max_length=8,
        choices=PilotFeedbackSeverity.choices,
        blank=True,
    )
    status = models.CharField(
        max_length=32,
        choices=PilotFeedbackStatus.choices,
        default=PilotFeedbackStatus.OPEN,
    )
    # Idempotency key within a batch. Empty means "no external key".
    external_key = models.CharField(max_length=128, blank=True, default="")
    external_key_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    # Stable reference only — no FK into documents to avoid domain cycles.
    evidence_document_version_public_id = models.UUIDField(null=True, blank=True)
    target_version = models.CharField(max_length=64, blank=True)
    workaround = models.TextField(blank=True)
    accepted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_pilot_feedback",
    )
    acceptance_note = models.CharField(max_length=512, blank=True)
    close_reason = models.CharField(max_length=255, blank=True)
    retest_result = models.CharField(max_length=32, blank=True)
    version_no = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "pilot_feedback"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "external_key", "external_key_slot"],
                name="pilot_feedback_batch_external_key_uniq",
            )
        ]
        indexes = [
            models.Index(fields=["batch", "status"]),
            models.Index(fields=["batch", "severity"]),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        key = (self.external_key or "").strip()
        self.external_key = key
        self.external_key_slot = 1 if key else None
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            fields = set(update_fields)
            fields.update({"external_key", "external_key_slot"})
            kwargs["update_fields"] = fields
        super().save(*args, **kwargs)
