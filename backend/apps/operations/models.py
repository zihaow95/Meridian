"""Operations models: monitoring scope, assignments, and metric definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.authorization.models.role import DataSensitivityLevel
from apps.platform.models.base import OrganizationOwnedModel


class MonitoringScopeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    CLOSED = "CLOSED", "Closed"


class MonitoringScopeType(models.TextChoices):
    PRODUCT = "PRODUCT", "Product"
    SKU = "SKU", "SKU"
    SKU_CHANNEL = "SKU_CHANNEL", "SKU channel"


class MonitoringAssignmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class CalculationType(models.TextChoices):
    SUM = "SUM", "Sum"
    AVERAGE = "AVERAGE", "Average"
    LAST = "LAST", "Last"
    RATIO = "RATIO", "Ratio"
    CONTROLLED_RULE = "CONTROLLED_RULE", "Controlled rule"


class MetricDefinitionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    RETIRED = "RETIRED", "Retired"


class PublishedMetricImmutable(Exception):
    pass


_FORBIDDEN_METRIC_PARAM_KEYS = frozenset(
    {"expression", "sql", "python", "python_code", "script"}
)


class MonitoringScope(OrganizationOwnedModel):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="monitoring_scopes",
    )
    product_version = models.ForeignKey(
        "products.ProductVersion",
        on_delete=models.PROTECT,
        related_name="monitoring_scopes",
    )
    owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="owned_monitoring_scopes",
    )
    effective_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=MonitoringScopeStatus.choices,
        default=MonitoringScopeStatus.ACTIVE,
    )
    source_decision_public_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_monitoring_scope"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_decision_public_id"],
                name="operations_monitoring_scope_project_decision_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.product_version_id}"


class MonitoringAssignment(OrganizationOwnedModel):
    monitoring_scope = models.ForeignKey(
        MonitoringScope,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    supervisor = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="monitoring_assignments",
    )
    product = models.ForeignKey(
        "products.ProductAsset",
        on_delete=models.PROTECT,
        related_name="monitoring_assignments",
    )
    sku = models.ForeignKey(
        "products.SKU",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="monitoring_assignments",
    )
    channel = models.ForeignKey(
        "products.ChannelConfiguration",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="monitoring_assignments",
    )
    scope_type = models.CharField(max_length=16, choices=MonitoringScopeType.choices)
    scope_key = models.CharField(max_length=128)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=MonitoringAssignmentStatus.choices,
        default=MonitoringAssignmentStatus.ACTIVE,
    )
    active_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    max_data_level = models.CharField(
        max_length=32,
        choices=DataSensitivityLevel.choices,
        default=DataSensitivityLevel.SENSITIVE_CONTROLLED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_monitoring_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "monitoring_scope",
                    "supervisor",
                    "scope_key",
                    "active_slot",
                ],
                name="operations_monitoring_assignment_active_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "supervisor", "status", "effective_from"],
                name="ops_mon_asg_sup_eff_idx",
            ),
            models.Index(
                fields=["product", "status"],
                name="ops_mon_asg_product_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.supervisor_id}:{self.scope_type}:{self.product_id}"

    def is_effective(self, *, as_of: datetime | None = None) -> bool:
        moment = as_of or timezone.now()
        if self.status != MonitoringAssignmentStatus.ACTIVE:
            return False
        if self.effective_from > moment:
            return False
        if self.effective_to is not None and self.effective_to <= moment:
            return False
        return True


def build_monitoring_scope_key(
    *,
    scope_type: str,
    product_id: int,
    sku_id: int | None = None,
    channel_id: int | None = None,
) -> str:
    if scope_type == MonitoringScopeType.PRODUCT:
        return f"PRODUCT:{product_id}"
    if scope_type == MonitoringScopeType.SKU:
        return f"SKU:{product_id}:{sku_id}"
    return f"SKU_CHANNEL:{product_id}:{sku_id}:{channel_id}"


class MetricDefinitionVersion(OrganizationOwnedModel):
    metric_code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    version_number = models.PositiveIntegerField()
    value_type = models.CharField(max_length=32)
    unit = models.CharField(max_length=32, blank=True, default="")
    currency = models.CharField(max_length=16, blank=True, default="")
    source_field_codes = models.JSONField(default=list)
    calculation_type = models.CharField(max_length=32, choices=CalculationType.choices)
    aggregation_rule = models.JSONField(default=dict)
    window_definition = models.JSONField(default=dict)
    coverage_requirement = models.JSONField(default=dict)
    controlled_rule_code = models.CharField(max_length=64, blank=True, default="")
    parameters_json = models.JSONField(default=dict)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=MetricDefinitionStatus.choices,
        default=MetricDefinitionStatus.DRAFT,
    )
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="metric_definitions_created",
    )
    published_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="metric_definitions_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_metric_definition_version"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "metric_code", "version_number"],
                name="operations_metric_def_org_code_ver_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "metric_code", "status"],
                name="ops_metric_code_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.metric_code}:v{self.version_number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.status == MetricDefinitionStatus.PUBLISHED and self.pk:
            previous = (
                MetricDefinitionVersion.objects.filter(pk=self.pk)
                .values(
                    "name",
                    "calculation_type",
                    "parameters_json",
                    "aggregation_rule",
                    "window_definition",
                    "coverage_requirement",
                    "source_field_codes",
                    "valid_from",
                    "valid_to",
                    "controlled_rule_code",
                )
                .first()
            )
            if previous is not None:
                for field, value in previous.items():
                    if getattr(self, field) != value:
                        raise PublishedMetricImmutable(
                            "Published metric definition cannot be edited."
                        )
        super().save(*args, **kwargs)


def validate_metric_parameters(parameters: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                full = f"{path}.{key}" if path else key
                if key.lower() in _FORBIDDEN_METRIC_PARAM_KEYS:
                    errors.append(f"Forbidden metric parameter: {full}")
                _walk(value, full)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                _walk(item, f"{path}[{index}]")

    _walk(parameters, "")
    return errors


def overlapping_published_metrics(
    *,
    organization_id: int,
    metric_code: str,
    valid_from: datetime,
    valid_to: datetime | None,
    exclude_id: int | None = None,
) -> models.QuerySet[MetricDefinitionVersion]:
    qs = MetricDefinitionVersion.objects.filter(
        organization_id=organization_id,
        metric_code=metric_code,
        status=MetricDefinitionStatus.PUBLISHED,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    # overlap if existing.valid_from < new.valid_to (or new open) AND
    # (existing.valid_to is null OR existing.valid_to > new.valid_from)
    if valid_to is None:
        qs = qs.filter(Q(valid_to__isnull=True) | Q(valid_to__gt=valid_from))
    else:
        qs = qs.filter(valid_from__lt=valid_to).filter(
            Q(valid_to__isnull=True) | Q(valid_to__gt=valid_from)
        )
    return qs
