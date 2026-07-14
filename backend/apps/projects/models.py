"""Minimal project instance models for phase 2 project creation."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class ProjectType(models.TextChoices):
    NEW_PRODUCT = "NEW_PRODUCT", "New product"
    PRODUCT_CHANGE = "PRODUCT_CHANGE", "Product change"


class ProjectStatus(models.TextChoices):
    INITIALIZING = "INITIALIZING", "Initializing"
    ACTIVE = "ACTIVE", "Active"
    DEFERRED = "DEFERRED", "Deferred"
    PASSED = "PASSED", "Passed"
    CLOSED = "CLOSED", "Closed"


class ProjectRole(models.TextChoices):
    LEADER = "LEADER", "Leader"
    DEPUTY = "DEPUTY", "Deputy"
    MEMBER = "MEMBER", "Member"


class Project(OrganizationOwnedModel):
    business_no = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    project_type = models.CharField(max_length=24, choices=ProjectType.choices)
    status = models.CharField(
        max_length=32,
        choices=ProjectStatus.choices,
        default=ProjectStatus.INITIALIZING,
    )
    candidate = models.OneToOneField(
        "opportunities.ProjectCandidate",
        on_delete=models.PROTECT,
        related_name="project",
    )
    leader = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="led_projects",
    )
    deputy_leader = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="deputy_led_projects",
    )
    product_asset = models.ForeignKey(
        "products.ProductAsset",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    product_draft = models.ForeignKey(
        "products.ProductChangeSet",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="projects",
    )
    idempotency_key = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_project"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "business_no"],
                name="projects_project_org_no_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "updated_at"]),
            models.Index(fields=["leader", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_no}:{self.name}"


class ProjectMember(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="members",
    )
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="project_memberships",
    )
    project_role = models.CharField(max_length=16, choices=ProjectRole.choices)
    # MySQL cannot enforce partial unique indexes; set only for active memberships.
    active_role_key = models.CharField(max_length=96, null=True, blank=True, unique=True)
    active_from = models.DateTimeField()
    active_to = models.DateTimeField(null=True, blank=True)
    appointed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="project_appointments",
    )

    class Meta:
        db_table = "projects_project_member"
        indexes = [
            models.Index(fields=["project", "project_role"]),
            models.Index(fields=["user", "active_from"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.user_id}:{self.project_role}"


class ProjectOpportunitySource(OrganizationOwnedModel):
    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name="opportunity_sources",
    )
    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        related_name="project_sources",
    )
    source_role = models.CharField(max_length=16)
    linked_at = models.DateTimeField()

    class Meta:
        db_table = "projects_project_opportunity_source"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "opportunity"],
                name="projects_opportunity_source_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "linked_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.opportunity_id}"
