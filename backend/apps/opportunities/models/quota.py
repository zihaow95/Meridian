"""Submission quota rules and per-opportunity quota ledger."""

from __future__ import annotations

from django.db import models

from apps.opportunities.models.opportunity import QuotaOwnerType
from apps.platform.models.base import OrganizationOwnedModel


class EnforcementMode(models.TextChoices):
    BLOCK = "BLOCK", "Block submission"
    WARN = "WARN", "Warn only"


class QuotaCountStatus(models.TextChoices):
    COUNTED = "COUNTED", "Counted"
    EXCLUDED = "EXCLUDED", "Excluded"


class SubmissionQuota(OrganizationOwnedModel):
    quarter = models.CharField(max_length=8)
    owner_type = models.CharField(max_length=16, choices=QuotaOwnerType.choices)
    owner_id = models.BigIntegerField()
    minimum_count = models.PositiveIntegerField(default=0)
    enforcement_mode = models.CharField(
        max_length=16,
        choices=EnforcementMode.choices,
        default=EnforcementMode.WARN,
    )
    rule_version = models.ForeignKey(
        "configuration.ConfigurationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="submission_quotas",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opportunities_submission_quota"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "quarter", "owner_type", "owner_id"],
                name="opportunities_submission_quota_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.quarter}:{self.owner_type}:{self.owner_id}"


class QuotaLedger(OrganizationOwnedModel):
    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        related_name="quota_entries",
    )
    quarter = models.CharField(max_length=8)
    owner_type = models.CharField(max_length=16, choices=QuotaOwnerType.choices)
    owner_id = models.BigIntegerField()
    count_status = models.CharField(
        max_length=16,
        choices=QuotaCountStatus.choices,
        default=QuotaCountStatus.COUNTED,
    )
    exclusion_reason = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "opportunities_quota_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity"],
                name="opportunities_quota_ledger_opportunity_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["owner_type", "owner_id", "quarter"]),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id}:{self.quarter}:{self.count_status}"
