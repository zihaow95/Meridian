"""Minimal product asset and draft models for phase 2."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class ProductSourceType(models.TextChoices):
    NEW_PROJECT = "NEW_PROJECT", "New project"
    LEGACY_IMPORT = "LEGACY_IMPORT", "Legacy import"


class ProductLifecycleStatus(models.TextChoices):
    DEVELOPING = "DEVELOPING", "Developing"
    ACTIVE = "ACTIVE", "Active"
    SUSPENDED = "SUSPENDED", "Suspended"
    RETIRED = "RETIRED", "Retired"


class DraftType(models.TextChoices):
    NEW_PRODUCT = "NEW_PRODUCT", "New product"
    PRODUCT_CHANGE = "PRODUCT_CHANGE", "Product change"


class DraftStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    LOCKED = "LOCKED", "Locked"


class ProductAsset(OrganizationOwnedModel):
    business_no = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    source_type = models.CharField(
        max_length=24,
        choices=ProductSourceType.choices,
        default=ProductSourceType.NEW_PROJECT,
    )
    lifecycle_status = models.CharField(
        max_length=24,
        choices=ProductLifecycleStatus.choices,
        default=ProductLifecycleStatus.DEVELOPING,
    )
    product_owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="owned_product_assets",
    )
    source_project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sourced_product_assets",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_product_asset"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "business_no"],
                name="products_asset_org_no_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "lifecycle_status", "updated_at"]),
            models.Index(fields=["product_owner", "lifecycle_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_no}:{self.name}"


class ProductDraft(OrganizationOwnedModel):
    product_asset = models.ForeignKey(
        ProductAsset,
        on_delete=models.PROTECT,
        related_name="drafts",
    )
    draft_type = models.CharField(max_length=24, choices=DraftType.choices)
    status = models.CharField(
        max_length=16,
        choices=DraftStatus.choices,
        default=DraftStatus.DRAFT,
    )
    target_product_asset = models.ForeignKey(
        ProductAsset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="change_drafts",
    )
    project_candidate = models.ForeignKey(
        "opportunities.ProjectCandidate",
        on_delete=models.PROTECT,
        related_name="product_drafts",
    )
    title = models.CharField(max_length=200)
    definition_summary = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_product_draft"
        constraints = [
            models.UniqueConstraint(
                fields=["project_candidate"],
                name="products_draft_candidate_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["product_asset", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.product_asset_id}:{self.title}"
