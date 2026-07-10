"""Product asset, version, change set, SKU, and channel configuration models."""

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


class ChangeSetType(models.TextChoices):
    NEW_PRODUCT = "NEW_PRODUCT", "New product"
    ITERATION = "ITERATION", "Product iteration"
    LEGACY_BASELINE = "LEGACY_BASELINE", "Legacy baseline"
    CORRECTION = "CORRECTION", "Correction"


class ChangeSetStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    LOCKED = "LOCKED", "Locked"
    IN_CONFIRMATION = "IN_CONFIRMATION", "In confirmation"
    APPROVED = "APPROVED", "Approved"
    PUBLISHED = "PUBLISHED", "Published"
    REJECTED = "REJECTED", "Rejected"


class CompletenessStatus(models.TextChoices):
    COMPLETE = "COMPLETE", "Complete"
    PARTIAL = "PARTIAL", "Partial"
    NEEDS_SUPPLEMENT = "NEEDS_SUPPLEMENT", "Needs supplement"


class ProductVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION", "Pending confirmation"
    APPROVED_PENDING_EFFECTIVE = "APPROVED_PENDING_EFFECTIVE", "Approved pending effective"
    EFFECTIVE = "EFFECTIVE", "Effective"
    INACTIVE = "INACTIVE", "Inactive"


class VersionScopeType(models.TextChoices):
    GLOBAL = "GLOBAL", "Global"
    CHANNEL = "CHANNEL", "Channel"


class VersionScopeStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planned"
    EFFECTIVE = "EFFECTIVE", "Effective"
    ENDED = "ENDED", "Ended"


class SKUStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class ChannelStatus(models.TextChoices):
    PLANNED = "PLANNED", "Planned"
    ON_SALE = "ON_SALE", "On sale"
    SUSPENDED = "SUSPENDED", "Suspended"
    OFF_SALE = "OFF_SALE", "Off sale"


_DRAFT_TYPE_BY_CHANGE_TYPE = {
    ChangeSetType.NEW_PRODUCT: DraftType.NEW_PRODUCT,
    ChangeSetType.ITERATION: DraftType.PRODUCT_CHANGE,
    ChangeSetType.LEGACY_BASELINE: DraftType.PRODUCT_CHANGE,
    ChangeSetType.CORRECTION: DraftType.PRODUCT_CHANGE,
}


class ProductAsset(OrganizationOwnedModel):
    business_no = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    brand_code = models.CharField(max_length=40, blank=True, default="")
    category_code = models.CharField(max_length=40, blank=True, default="")
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
    primary_version = models.ForeignKey(
        "products.ProductVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="primary_for_assets",
    )
    source_project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sourced_product_assets",
    )
    retired_at = models.DateTimeField(null=True, blank=True)
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
            models.Index(fields=["organization", "lifecycle_status", "category_code"]),
            models.Index(fields=["product_owner", "lifecycle_status"]),
            models.Index(fields=["name"]),
            models.Index(fields=["brand_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.business_no}:{self.name}"


class ProductChangeSet(OrganizationOwnedModel):
    change_type = models.CharField(max_length=24, choices=ChangeSetType.choices)
    status = models.CharField(
        max_length=24,
        choices=ChangeSetStatus.choices,
        default=ChangeSetStatus.DRAFT,
    )
    product = models.ForeignKey(
        ProductAsset,
        on_delete=models.PROTECT,
        related_name="change_sets",
    )
    target_product_asset = models.ForeignKey(
        ProductAsset,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="targeted_change_sets",
    )
    project_candidate = models.ForeignKey(
        "opportunities.ProjectCandidate",
        on_delete=models.PROTECT,
        related_name="product_change_sets",
    )
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="product_change_sets",
    )
    migration_batch_id = models.BigIntegerField(null=True, blank=True)
    base_version = models.ForeignKey(
        "products.ProductVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="iteration_change_sets",
    )
    base_fingerprint = models.CharField(max_length=64, blank=True, default="")
    change_scope = models.JSONField(default=dict, blank=True)
    completeness_status = models.CharField(
        max_length=24,
        choices=CompletenessStatus.choices,
        blank=True,
        default="",
    )
    approval_basis_type = models.CharField(max_length=40, blank=True, default="")
    approval_basis_id = models.BigIntegerField(null=True, blank=True)
    title = models.CharField(max_length=200)
    definition_summary = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_product_change_set"
        constraints = [
            models.UniqueConstraint(
                fields=["project_candidate"],
                name="products_draft_candidate_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["product", "status"], name="products_pr_product_81d130_idx"),
            models.Index(fields=["project", "status"], name="products_pr_project_132b56_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.product_id}:{self.title}"

    @property
    def draft_type(self) -> str:
        return _DRAFT_TYPE_BY_CHANGE_TYPE.get(
            ChangeSetType(self.change_type),
            DraftType.PRODUCT_CHANGE,
        )

    @property
    def product_asset(self) -> ProductAsset:
        return self.product


class ProductDraft(ProductChangeSet):
    """Phase 2 compatibility alias over ``ProductChangeSet``."""

    class Meta:
        proxy = True


class ProductVersion(OrganizationOwnedModel):
    product = models.ForeignKey(
        ProductAsset,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_code = models.CharField(max_length=40)
    version_name = models.CharField(max_length=120)
    status = models.CharField(max_length=32, choices=ProductVersionStatus.choices)
    change_set = models.ForeignKey(
        ProductChangeSet,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="draft_versions",
    )
    supersedes_version = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by_versions",
    )
    definition_summary = models.TextField(blank=True, default="")
    shelf_life_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    shelf_life_unit = models.CharField(max_length=16, blank=True, default="")
    storage_condition = models.TextField(blank=True, default="")
    standard_code = models.CharField(max_length=80, blank=True, default="")
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    approval_basis_type = models.CharField(max_length=40, blank=True, default="")
    approval_basis_id = models.BigIntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="published_product_versions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_product_version"
        constraints = [
            models.UniqueConstraint(
                fields=["product", "version_code"],
                name="products_version_product_code_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["product", "status"]),
            models.Index(fields=["organization", "status", "updated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.product_id}:{self.version_code}"


class ProductVersionScope(OrganizationOwnedModel):
    product_version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="scopes",
    )
    scope_type = models.CharField(max_length=16, choices=VersionScopeType.choices)
    channel_code = models.CharField(max_length=40, blank=True, default="")
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=VersionScopeStatus.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_product_version_scope"
        indexes = [
            models.Index(fields=["product_version", "status"]),
            models.Index(fields=["organization", "scope_type", "channel_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.product_version_id}:{self.scope_type}"


class SKU(OrganizationOwnedModel):
    product_version = models.ForeignKey(
        ProductVersion,
        on_delete=models.PROTECT,
        related_name="skus",
    )
    sku_code = models.CharField(max_length=40)
    name = models.CharField(max_length=200)
    specification = models.CharField(max_length=160, blank=True, default="")
    net_content_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    net_content_unit = models.CharField(max_length=20, blank=True, default="")
    sales_unit = models.CharField(max_length=40, blank=True, default="")
    inner_packaging = models.TextField(blank=True, default="")
    outer_packaging = models.TextField(blank=True, default="")
    case_pack_relation = models.CharField(max_length=100, blank=True, default="")
    barcode = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=SKUStatus.choices,
        default=SKUStatus.DRAFT,
    )
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    supersedes_sku = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by_skus",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_sku"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "sku_code"],
                name="products_sku_org_code_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["product_version", "status"]),
            models.Index(fields=["organization", "barcode"]),
            models.Index(fields=["product_version", "name", "specification"]),
        ]

    def __str__(self) -> str:
        return f"{self.sku_code}:{self.name}"


class ChannelConfiguration(OrganizationOwnedModel):
    sku = models.ForeignKey(
        SKU,
        on_delete=models.PROTECT,
        related_name="channel_configurations",
    )
    channel_code = models.CharField(max_length=40)
    configuration_version = models.PositiveIntegerField()
    suggested_retail_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
    )
    channel_selling_points = models.TextField(blank=True, default="")
    channel_status = models.CharField(max_length=24, choices=ChannelStatus.choices)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    supersedes_config = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_by_configs",
    )
    change_set = models.ForeignKey(
        ProductChangeSet,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="channel_configurations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "products_channel_configuration"
        constraints = [
            models.UniqueConstraint(
                fields=["sku", "channel_code", "configuration_version"],
                name="products_channel_config_version_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["sku", "channel_code", "channel_status"]),
            models.Index(fields=["organization", "channel_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.sku_id}:{self.channel_code}:v{self.configuration_version}"
