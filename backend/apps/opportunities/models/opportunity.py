"""Long-lived product opportunity asset."""

from __future__ import annotations

from django.db import models

from apps.authorization.models.role import DataSensitivityLevel
from apps.platform.models.base import OrganizationOwnedModel


class InitialType(models.TextChoices):
    NEW = "NEW", "New product"
    ITERATION = "ITERATION", "Product iteration"
    UNDECIDED = "UNDECIDED", "Undecided"


class QuotaOwnerType(models.TextChoices):
    USER = "USER", "User"
    DEPARTMENT = "DEPARTMENT", "Department"


class ProposalStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    IN_REVIEW = "IN_REVIEW", "In review"
    NEEDS_INFO = "NEEDS_INFO", "Needs info"
    DEFERRED = "DEFERRED", "Deferred"
    PASSED = "PASSED", "Passed"
    CASE_APPROVED = "CASE_APPROVED", "Case approved"


class Opportunity(OrganizationOwnedModel):
    business_no = models.CharField(max_length=32)
    title = models.CharField(max_length=200)
    public_summary = models.TextField(blank=True, default="")
    initial_type = models.CharField(
        max_length=32,
        choices=InitialType.choices,
        default=InitialType.UNDECIDED,
    )
    proposal_owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="owned_opportunities",
    )
    owner_department = models.ForeignKey(
        "identity.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="opportunities",
    )
    quota_owner_type = models.CharField(max_length=16, choices=QuotaOwnerType.choices)
    quota_owner_id = models.BigIntegerField()
    proposal_status = models.CharField(
        max_length=32,
        choices=ProposalStatus.choices,
        default=ProposalStatus.DRAFT,
    )
    current_version = models.ForeignKey(
        "opportunities.ProposalVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for",
    )
    visibility_level = models.CharField(
        max_length=32,
        choices=DataSensitivityLevel.choices,
        default=DataSensitivityLevel.INTERNAL,
    )
    version_no = models.PositiveIntegerField(default=1)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opportunities_opportunity"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "business_no"],
                name="opportunities_opportunity_org_no_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "proposal_status", "updated_at"]),
            models.Index(fields=["proposal_owner", "proposal_status"]),
            models.Index(fields=["quota_owner_type", "quota_owner_id", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_no}:{self.title}"
