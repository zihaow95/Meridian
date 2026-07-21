"""Operations models: monitoring scope, metrics, facts, aggregates, and risk."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.authorization.models.role import DataSensitivityLevel
from apps.operations.errors import SnapshotImmutable
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


_FORBIDDEN_METRIC_PARAM_KEYS = frozenset({"expression", "sql", "python", "python_code", "script"})


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


class OperatingFactStatus(models.TextChoices):
    VALID = "VALID", "Valid"
    SUPERSEDED = "SUPERSEDED", "Superseded"
    INVALID = "INVALID", "Invalid"


class ManualEffectiveValueStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    REVOKED = "REVOKED", "Revoked"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class OperatingFact(OrganizationOwnedModel):
    sku = models.ForeignKey(
        "products.SKU",
        on_delete=models.PROTECT,
        related_name="operating_facts",
    )
    channel = models.ForeignKey(
        "products.ChannelConfiguration",
        on_delete=models.PROTECT,
        related_name="operating_facts",
    )
    metric_definition = models.ForeignKey(
        MetricDefinitionVersion,
        on_delete=models.PROTECT,
        related_name="operating_facts",
    )
    period_granularity = models.CharField(max_length=12)
    period_start = models.DateField()
    period_end = models.DateField()
    numeric_value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    text_value = models.TextField(blank=True, default="")
    unit = models.CharField(max_length=32, blank=True, default="")
    currency = models.CharField(max_length=16, blank=True, default="")
    source = models.ForeignKey(
        "integrations.DataSource",
        on_delete=models.PROTECT,
        related_name="operating_facts",
    )
    batch = models.ForeignKey(
        "integrations.IngestionBatch",
        on_delete=models.PROTECT,
        related_name="operating_facts",
    )
    source_record_key = models.CharField(max_length=128)
    fact_status = models.CharField(
        max_length=16,
        choices=OperatingFactStatus.choices,
        default=OperatingFactStatus.VALID,
    )
    active_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    source_timestamp = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_operating_fact"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "source",
                    "source_record_key",
                    "metric_definition",
                    "sku",
                    "channel",
                    "period_granularity",
                    "period_start",
                    "period_end",
                    "active_slot",
                ],
                name="operations_operating_fact_active_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "sku", "channel", "metric_definition", "period_start"],
                name="ops_fact_scope_period_idx",
            ),
            models.Index(
                fields=["source", "source_record_key", "fact_status"],
                name="ops_fact_source_key_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.source_record_key}:{self.fact_status}"


class ManualEffectiveValue(OrganizationOwnedModel):
    sku = models.ForeignKey(
        "products.SKU",
        on_delete=models.PROTECT,
        related_name="manual_effective_values",
    )
    channel = models.ForeignKey(
        "products.ChannelConfiguration",
        on_delete=models.PROTECT,
        related_name="manual_effective_values",
    )
    metric_definition = models.ForeignKey(
        MetricDefinitionVersion,
        on_delete=models.PROTECT,
        related_name="manual_effective_values",
    )
    period_granularity = models.CharField(max_length=12)
    period_start = models.DateField()
    period_end = models.DateField()
    original_fact = models.ForeignKey(
        OperatingFact,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="manual_overrides",
    )
    numeric_value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    text_value = models.TextField(blank=True, default="")
    reason = models.TextField()
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=ManualEffectiveValueStatus.choices,
        default=ManualEffectiveValueStatus.ACTIVE,
    )
    active_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="manual_effective_values_confirmed",
    )
    confirmed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_manual_effective_value"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "sku",
                    "channel",
                    "metric_definition",
                    "period_granularity",
                    "period_start",
                    "period_end",
                    "active_slot",
                ],
                name="operations_manual_value_active_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "sku", "channel", "status"],
                name="ops_manual_scope_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sku_id}:{self.metric_definition_id}:{self.status}"


class AggregateGrainType(models.TextChoices):
    SKU = "SKU", "SKU"
    PRODUCT = "PRODUCT", "Product"


class AggregateStatus(models.TextChoices):
    OK = "OK", "Ok"
    NOT_COMPARABLE = "NOT_COMPARABLE", "Not comparable"
    INSUFFICIENT = "INSUFFICIENT", "Insufficient"


class MetricAggregate(OrganizationOwnedModel):
    grain_type = models.CharField(max_length=16, choices=AggregateGrainType.choices)
    grain_id = models.UUIDField()
    channel = models.ForeignKey(
        "products.ChannelConfiguration",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="metric_aggregates",
    )
    channel_key = models.CharField(max_length=64, default="ALL")
    metric_definition = models.ForeignKey(
        MetricDefinitionVersion,
        on_delete=models.PROTECT,
        related_name="metric_aggregates",
    )
    period_granularity = models.CharField(max_length=12)
    period_start = models.DateField()
    period_end = models.DateField()
    value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True, default="")
    currency = models.CharField(max_length=16, blank=True, default="")
    status = models.CharField(
        max_length=32,
        choices=AggregateStatus.choices,
        default=AggregateStatus.OK,
    )
    coverage_rate = models.DecimalField(max_digits=8, decimal_places=6, default=0)
    source_count = models.PositiveIntegerField(default=0)
    has_manual_value = models.BooleanField(default=False)
    contributors_json = models.JSONField(default=list)
    calculated_at = models.DateTimeField()
    calculation_run_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_metric_aggregate"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "organization",
                    "grain_type",
                    "grain_id",
                    "channel_key",
                    "metric_definition",
                    "period_granularity",
                    "period_start",
                    "period_end",
                ],
                name="operations_metric_aggregate_scope_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "metric_definition", "period_start", "period_end"],
                name="ops_agg_org_metric_period_idx",
            ),
            models.Index(
                fields=["organization", "grain_type", "grain_id", "period_start"],
                name="ops_agg_grain_period_idx",
            ),
            models.Index(
                fields=["organization", "channel", "period_start"],
                name="ops_agg_channel_period_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.grain_type}:{self.grain_id}:{self.metric_definition_id}"


class OperatingDataSnapshot(OrganizationOwnedModel):
    purpose = models.CharField(max_length=64)
    scope_json = models.JSONField(default=dict)
    periods_json = models.JSONField(default=list)
    metric_codes = models.JSONField(default=list)
    payload_json = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="operating_data_snapshots_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "operations_operating_data_snapshot"
        indexes = [
            models.Index(
                fields=["organization", "purpose", "created_at"],
                name="ops_snapshot_org_purpose_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.purpose}:{self.content_hash[:12]}"

    def compute_content_hash(self) -> str:
        canonical = {
            "purpose": self.purpose,
            "scope": self.scope_json,
            "periods": self.periods_json,
            "metric_codes": self.metric_codes,
            "payload": self.payload_json,
        }
        encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise SnapshotImmutable()
        if not self.content_hash:
            self.content_hash = self.compute_content_hash()
        super().save(*args, **kwargs)


class RiskRuleStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"
    RETIRED = "RETIRED", "Retired"


class RiskSignalStatus(models.TextChoices):
    NEW = "NEW", "New"
    VIEWED = "VIEWED", "Viewed"
    CLOSED = "CLOSED", "Closed"
    ESCALATED = "ESCALATED", "Escalated"


class RiskCoverageStatus(models.TextChoices):
    SUFFICIENT = "SUFFICIENT", "Sufficient"
    INSUFFICIENT = "INSUFFICIENT", "Insufficient"


class PublishedRiskRuleImmutable(Exception):
    pass


_FORBIDDEN_RISK_PARAM_KEYS = frozenset({"expression", "sql", "python", "python_code", "script"})


class RiskRuleVersion(OrganizationOwnedModel):
    rule_code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    version_number = models.PositiveIntegerField()
    metric_codes = models.JSONField(default=list)
    evaluator_code = models.CharField(max_length=64)
    parameters_json = models.JSONField(default=dict)
    scope_type = models.CharField(max_length=16, choices=MonitoringScopeType.choices)
    status = models.CharField(
        max_length=16,
        choices=RiskRuleStatus.choices,
        default=RiskRuleStatus.DRAFT,
    )
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="risk_rules_created",
    )
    published_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="risk_rules_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_risk_rule_version"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "rule_code", "version_number"],
                name="operations_risk_rule_org_code_ver_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "rule_code", "status"],
                name="ops_risk_rule_code_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rule_code}:v{self.version_number}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.status == RiskRuleStatus.PUBLISHED and self.pk:
            previous = (
                RiskRuleVersion.objects.filter(pk=self.pk)
                .values(
                    "name",
                    "metric_codes",
                    "evaluator_code",
                    "parameters_json",
                    "scope_type",
                    "valid_from",
                    "valid_to",
                )
                .first()
            )
            if previous is not None:
                for field, value in previous.items():
                    if getattr(self, field) != value:
                        raise PublishedRiskRuleImmutable(
                            "Published risk rule cannot be edited."
                        )
        super().save(*args, **kwargs)


def validate_risk_parameters(parameters: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                full = f"{path}.{key}" if path else key
                if key.lower() in _FORBIDDEN_RISK_PARAM_KEYS:
                    errors.append(f"Forbidden risk parameter: {full}")
                _walk(value, full)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                _walk(item, f"{path}[{index}]")

    _walk(parameters, "")
    return errors


def build_risk_scope_key(
    *,
    scope_type: str,
    scope_id: str,
    channel_id: str | None = None,
) -> str:
    if scope_type == MonitoringScopeType.PRODUCT:
        return f"PRODUCT:{scope_id}"
    if scope_type == MonitoringScopeType.SKU:
        return f"SKU:{scope_id}"
    return f"SKU_CHANNEL:{scope_id}:{channel_id or 'NONE'}"


class RiskSignal(OrganizationOwnedModel):
    rule_version = models.ForeignKey(
        RiskRuleVersion,
        on_delete=models.PROTECT,
        related_name="signals",
    )
    scope_type = models.CharField(max_length=16, choices=MonitoringScopeType.choices)
    scope_id = models.UUIDField()
    channel = models.ForeignKey(
        "products.ChannelConfiguration",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="risk_signals",
    )
    scope_key = models.CharField(max_length=160)
    period_granularity = models.CharField(max_length=12, default="QUARTER")
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=RiskSignalStatus.choices,
        default=RiskSignalStatus.NEW,
    )
    actual_value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    threshold_value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    formula_snapshot = models.JSONField(default=dict)
    data_snapshot = models.ForeignKey(
        OperatingDataSnapshot,
        on_delete=models.PROTECT,
        related_name="risk_signals",
    )
    coverage_status = models.CharField(
        max_length=16,
        choices=RiskCoverageStatus.choices,
        default=RiskCoverageStatus.SUFFICIENT,
    )
    closed_reason = models.TextField(blank=True, default="")
    closed_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="risk_signals_closed",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    display_recalculated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_risk_signal"
        constraints = [
            models.UniqueConstraint(
                fields=["rule_version", "scope_key", "period_start", "period_end"],
                name="operations_risk_signal_rule_scope_period_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "period_start"],
                name="ops_rsig_org_status_idx",
            ),
            models.Index(
                fields=["organization", "scope_key", "period_start"],
                name="ops_rsig_scope_period_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rule_version_id}:{self.scope_key}:{self.period_start}"


class SignalRecalculation(OrganizationOwnedModel):
    signal = models.ForeignKey(
        RiskSignal,
        on_delete=models.PROTECT,
        related_name="recalculations",
    )
    reason = models.CharField(max_length=128)
    old_actual_value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    new_actual_value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    old_threshold_value = models.DecimalField(
        max_digits=24, decimal_places=6, null=True, blank=True
    )
    new_threshold_value = models.DecimalField(
        max_digits=24, decimal_places=6, null=True, blank=True
    )
    impact_summary = models.TextField()
    triggered_by_fact = models.ForeignKey(
        OperatingFact,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="signal_recalculations",
    )
    triggered_by_manual = models.ForeignKey(
        ManualEffectiveValue,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="signal_recalculations",
    )
    calculated_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "operations_signal_recalculation"
        indexes = [
            models.Index(
                fields=["organization", "signal", "calculated_at"],
                name="ops_signal_recalc_signal_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.signal_id}:{self.reason}"


class OperatingIssueStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ANALYZING = "ANALYZING", "Analyzing"
    OBSERVING = "OBSERVING", "Observing"
    ACTIONING = "ACTIONING", "Actioning"
    CONVERTED_TO_PROPOSAL = "CONVERTED_TO_PROPOSAL", "Converted to proposal"
    RETIREMENT_REVIEW = "RETIREMENT_REVIEW", "Retirement review"
    CLOSED = "CLOSED", "Closed"


class IssueSourceType(models.TextChoices):
    RISK_SIGNAL = "RISK_SIGNAL", "Risk signal"
    PRODUCT_PORTFOLIO_REVIEW = "PRODUCT_PORTFOLIO_REVIEW", "Product portfolio review"
    QUALITY_COMPLIANCE = "QUALITY_COMPLIANCE", "Quality compliance"
    STRATEGIC = "STRATEGIC", "Strategic"
    DIRECT = "DIRECT", "Direct"


class RecommendationType(models.TextChoices):
    CONTINUE_OBSERVING = "CONTINUE_OBSERVING", "Continue observing"
    ADJUST_PRICE = "ADJUST_PRICE", "Adjust price"
    ADJUST_CHANNEL = "ADJUST_CHANNEL", "Adjust channel"
    ADJUST_MARKET = "ADJUST_MARKET", "Adjust market"
    ADJUST_SUPPLY = "ADJUST_SUPPLY", "Adjust supply"
    ITERATE = "ITERATE", "Iterate"
    SUSPEND = "SUSPEND", "Suspend"
    RETIRE = "RETIRE", "Retire"
    CLOSE = "CLOSE", "Close"


class OperatingIssue(OrganizationOwnedModel):
    business_no = models.CharField(max_length=32)
    title = models.CharField(max_length=255)
    product = models.ForeignKey(
        "products.ProductAsset",
        on_delete=models.PROTECT,
        related_name="operating_issues",
    )
    status = models.CharField(
        max_length=32,
        choices=OperatingIssueStatus.choices,
        default=OperatingIssueStatus.PENDING,
    )
    owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="operating_issues_owned",
    )
    source_type = models.CharField(max_length=32, choices=IssueSourceType.choices)
    source_materials_json = models.JSONField(default=dict, blank=True)
    phenomenon_summary = models.TextField()
    recommendation_type = models.CharField(
        max_length=32,
        choices=RecommendationType.choices,
        blank=True,
        default="",
    )
    data_snapshot = models.ForeignKey(
        OperatingDataSnapshot,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="operating_issues",
    )
    target_review_at = models.DateTimeField(null=True, blank=True)
    linked_opportunity_id = models.UUIDField(null=True, blank=True)
    linked_project_id = models.UUIDField(null=True, blank=True)
    linked_product_version_id = models.UUIDField(null=True, blank=True)
    linked_effective_from = models.DateTimeField(null=True, blank=True)
    version_no = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="operating_issues_created",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="operating_issues_closed",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_operating_issue"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "business_no"],
                name="operations_issue_org_business_no_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "status", "target_review_at"],
                name="ops_issue_status_review_idx",
            ),
            models.Index(
                fields=["organization", "product", "status"],
                name="ops_issue_product_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.business_no}:{self.status}"


class IssueSignal(OrganizationOwnedModel):
    issue = models.ForeignKey(
        OperatingIssue,
        on_delete=models.PROTECT,
        related_name="signal_links",
    )
    signal = models.ForeignKey(
        RiskSignal,
        on_delete=models.PROTECT,
        related_name="issue_links",
    )
    is_primary = models.BooleanField(default=False)
    active_primary_slot = models.PositiveSmallIntegerField(null=True, blank=True)
    linked_at = models.DateTimeField()
    unlinked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_issue_signal"
        constraints = [
            models.UniqueConstraint(
                fields=["signal", "active_primary_slot"],
                name="operations_issue_signal_active_primary_uniq",
            ),
            models.UniqueConstraint(
                fields=["issue", "signal"],
                name="operations_issue_signal_pair_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "issue", "is_primary"],
                name="ops_issue_signal_issue_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.issue_id}:{self.signal_id}"


class IssueDecision(OrganizationOwnedModel):
    issue = models.ForeignKey(
        OperatingIssue,
        on_delete=models.PROTECT,
        related_name="decisions",
    )
    recommendation_type = models.CharField(max_length=32, choices=RecommendationType.choices)
    action_summary = models.TextField()
    responsible_user = models.ForeignKey(
        "identity.User",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="operating_issue_decisions",
    )
    planned_at = models.DateTimeField(null=True, blank=True)
    materials_snapshot_json = models.JSONField(default=dict, blank=True)
    decided_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="operating_issue_decisions_made",
    )
    decided_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "operations_issue_decision"
        indexes = [
            models.Index(
                fields=["organization", "issue", "decided_at"],
                name="ops_issue_decision_issue_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.issue_id}:{self.recommendation_type}"


class IssueConversionType(models.TextChoices):
    ITERATION_PROPOSAL = "ITERATION_PROPOSAL", "Iteration proposal"


class IssueConversion(OrganizationOwnedModel):
    issue = models.ForeignKey(
        OperatingIssue,
        on_delete=models.PROTECT,
        related_name="conversions",
    )
    conversion_type = models.CharField(max_length=32, choices=IssueConversionType.choices)
    opportunity_public_id = models.UUIDField()
    source_snapshot_json = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128)
    converted_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="issue_conversions",
    )
    converted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "operations_issue_conversion"
        constraints = [
            models.UniqueConstraint(
                fields=["issue", "conversion_type"],
                name="operations_issue_conversion_type_uniq",
            ),
            models.UniqueConstraint(
                fields=["organization", "idempotency_key"],
                name="operations_issue_conversion_idem_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["organization", "opportunity_public_id"],
                name="ops_issue_conv_opp_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.issue_id}:{self.conversion_type}"
