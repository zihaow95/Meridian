"""Project candidate: the pre-project proposal that carries case assessment."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class CandidateType(models.TextChoices):
    NEW_PRODUCT = "NEW_PRODUCT", "New product"
    PRODUCT_CHANGE = "PRODUCT_CHANGE", "Product change"


class CandidateStatus(models.TextChoices):
    AWAITING_ASSIGNMENT = "AWAITING_ASSIGNMENT", "Awaiting assignment"
    ASSESSING = "ASSESSING", "Assessing"
    IN_PROJECT_REVIEW = "IN_PROJECT_REVIEW", "In project review"
    NEEDS_INFO = "NEEDS_INFO", "Needs info"
    DEFERRED = "DEFERRED", "Deferred"
    PASSED = "PASSED", "Passed"
    SOURCE_RECONFIRM_REQUIRED = "SOURCE_RECONFIRM_REQUIRED", "Source reconfirm required"
    PROJECT_CREATED = "PROJECT_CREATED", "Project created"


class SourceRole(models.TextChoices):
    PRIMARY = "PRIMARY", "Primary"
    ADDITIONAL = "ADDITIONAL", "Additional"


class ProjectCandidate(OrganizationOwnedModel):
    business_no = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    candidate_type = models.CharField(
        max_length=20,
        choices=CandidateType.choices,
        default=CandidateType.NEW_PRODUCT,
    )
    target_product_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=CandidateStatus.choices,
        default=CandidateStatus.AWAITING_ASSIGNMENT,
    )
    case_owner = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="led_case_candidates",
    )
    deputy_leader = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deputy_case_candidates",
    )
    proposed_schedule = models.JSONField(default=dict, blank=True)
    resource_risk_summary = models.TextField(blank=True, default="")
    # Set only when the project instance is created (Task 2.7); nullable + unique.
    project_id = models.BigIntegerField(null=True, blank=True)
    version_no = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opportunities_project_candidate"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "business_no"],
                name="opportunities_candidate_org_no_uniq",
            ),
            models.UniqueConstraint(
                fields=["project_id"],
                condition=models.Q(project_id__isnull=False),
                name="opportunities_candidate_project_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "updated_at"]),
            models.Index(fields=["case_owner", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_no}:{self.name}"


class CandidateSource(OrganizationOwnedModel):
    candidate = models.ForeignKey(
        ProjectCandidate,
        on_delete=models.PROTECT,
        related_name="sources",
    )
    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        related_name="candidate_links",
    )
    source_role = models.CharField(
        max_length=16,
        choices=SourceRole.choices,
        default=SourceRole.PRIMARY,
    )
    is_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField()
    linked_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="linked_candidate_sources",
    )

    class Meta:
        db_table = "opportunities_candidate_source"
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "opportunity"],
                name="opportunities_candidate_source_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.candidate_id}:{self.opportunity_id}"
