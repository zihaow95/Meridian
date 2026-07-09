"""Reconsideration records that reopen a passed subject in a new review cycle."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class Reconsideration(OrganizationOwnedModel):
    subject_type = models.CharField(max_length=32)
    original_subject_public_id = models.UUIDField()
    original_cycle = models.ForeignKey(
        "stage_gates.StageGateInstance",
        on_delete=models.PROTECT,
        related_name="reconsiderations_as_original",
    )
    new_cycle = models.ForeignKey(
        "stage_gates.StageGateInstance",
        on_delete=models.PROTECT,
        related_name="reconsiderations_as_new",
    )
    target_stage_code = models.CharField(max_length=32)
    reason = models.TextField(blank=True, default="")
    eligibility_basis = models.CharField(max_length=64, blank=True, default="")
    adjustment_note = models.TextField(blank=True, default="")
    initiated_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="reconsiderations_started",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "opportunities_reconsideration"
        indexes = [
            models.Index(fields=["subject_type", "original_subject_public_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.subject_type}:{self.original_subject_public_id}"
