"""Permission-filtered query helpers for operations list endpoints."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import QuerySet

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import LEVEL_RANK, DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.integrations.models import DataSource, IngestionBatch, IngestionRow, IngestionRowStatus
from apps.operations.models import (
    MetricDefinitionVersion,
    OperatingIssue,
    RiskRuleVersion,
    RiskSignal,
)
from apps.operations.policies.identity_provider import resolve_effective_assignments
from apps.products.models import SKU, ProductAsset

_INGESTION_BATCH_READ_LIKE_ACTIONS: tuple[str, ...] = (
    "ingestion_batch.create",
    "ingestion_batch.confirm",
    "ingestion_batch.retry",
    "mapping.resolve",
)


def _org_action_allowed(
    user: User,
    *,
    action: str,
    resource_type: str,
    sensitivity_level: str = DataSensitivityLevel.INTERNAL,
) -> bool:
    decision = authorize(
        subject_for(user),
        action=action,
        resource=ResourceDescriptor(
            resource_type=resource_type,
            public_id=None,
            organization_id=user.organization_id,
            sensitivity_level=sensitivity_level,
        ),
        context=AuthorizationContext.current(),
    )
    return decision.allowed


def _assigned_product_ids(user: User) -> set[int]:
    assignments = resolve_effective_assignments(user=user, organization_id=user.organization_id)
    return {row.product_id for row in assignments if row.product_id}


def _assigned_sku_public_ids(user: User) -> set[UUID]:
    assignments = resolve_effective_assignments(user=user, organization_id=user.organization_id)
    sku_ids = {row.sku_id for row in assignments if row.sku_id}
    if not sku_ids:
        product_ids = _assigned_product_ids(user)
        if not product_ids:
            return set()
        return set(
            SKU.objects.filter(
                organization_id=user.organization_id,
                product_version__product_id__in=product_ids,
            ).values_list("public_id", flat=True)
        )
    return set(
        SKU.objects.filter(id__in=sku_ids, organization_id=user.organization_id).values_list(
            "public_id", flat=True
        )
    )


def list_visible_data_sources(user: User) -> QuerySet[DataSource]:
    qs = DataSource.objects.filter(organization_id=user.organization_id).order_by(
        "source_code", "id"
    )
    if _org_action_allowed(user, action="data_source.configure", resource_type="data_source"):
        return qs
    return qs.none()


def list_visible_metric_definitions(user: User) -> QuerySet[MetricDefinitionVersion]:
    qs = MetricDefinitionVersion.objects.filter(organization_id=user.organization_id).order_by(
        "metric_code", "-version_number", "id"
    )
    if _org_action_allowed(user, action="metric_rule.configure", resource_type="metric_definition"):
        return qs
    return qs.none()


def list_visible_risk_rules(user: User) -> QuerySet[RiskRuleVersion]:
    qs = RiskRuleVersion.objects.filter(organization_id=user.organization_id).order_by(
        "rule_code", "-version_number", "id"
    )
    if _org_action_allowed(user, action="metric_rule.configure", resource_type="metric_definition"):
        return qs
    return qs.none()


def list_visible_risk_signals(user: User, **filters: Any) -> QuerySet[RiskSignal]:
    qs = (
        RiskSignal.objects.filter(organization_id=user.organization_id)
        .select_related("rule_version", "channel")
        .order_by("-created_at", "id")
    )
    status = filters.get("status")
    if status:
        qs = qs.filter(status=status)

    if _org_action_allowed(
        user,
        action="risk_signal.read",
        resource_type="risk_signal",
        sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
    ):
        return qs

    sku_public_ids = _assigned_sku_public_ids(user)
    if not sku_public_ids:
        return qs.none()
    return qs.filter(scope_id__in=sku_public_ids)


def list_visible_operating_issues(user: User, **filters: Any) -> QuerySet[OperatingIssue]:
    qs = (
        OperatingIssue.objects.filter(organization_id=user.organization_id)
        .select_related("product", "owner")
        .order_by("-created_at", "id")
    )
    status = filters.get("status")
    if status:
        qs = qs.filter(status=status)

    if _org_action_allowed(
        user,
        action="operating_issue.create",
        resource_type="operating_issue",
        sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
    ) or _org_action_allowed(
        user,
        action="operating_issue.analyze",
        resource_type="operating_issue",
        sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
    ):
        return qs

    product_ids = _assigned_product_ids(user)
    if not product_ids:
        return qs.none()
    return qs.filter(product_id__in=product_ids)


def get_visible_ingestion_batch(user: User, public_id: UUID) -> IngestionBatch | None:
    """Return the batch if the user holds any read-like ingestion action for its source."""

    batch = (
        IngestionBatch.objects.select_related("source")
        .filter(organization_id=user.organization_id, public_id=public_id)
        .first()
    )
    if batch is None:
        return None

    resource = ResourceDescriptor(
        resource_type="ingestion_batch",
        public_id=batch.public_id,
        organization_id=user.organization_id,
        sensitivity_level=batch.source.sensitivity_level or DataSensitivityLevel.INTERNAL,
        metadata={"source_public_id": str(batch.source.public_id)},
    )
    context = AuthorizationContext.current()
    subject = subject_for(user)
    for action in _INGESTION_BATCH_READ_LIKE_ACTIONS:
        if authorize(subject, action=action, resource=resource, context=context).allowed:
            return batch
    return None


def list_visible_ingestion_batch_rows(user: User, public_id: UUID) -> QuerySet[IngestionRow] | None:
    """Return ordered batch rows when the batch is visible; otherwise None."""

    batch = get_visible_ingestion_batch(user, public_id)
    if batch is None:
        return None
    return IngestionRow.objects.filter(batch=batch).order_by("row_number", "id")


def list_unmapped_ingestion_rows(user: User) -> QuerySet[IngestionRow]:
    qs = (
        IngestionRow.objects.filter(
            organization_id=user.organization_id,
            status=IngestionRowStatus.UNMAPPED,
        )
        .select_related("batch", "batch__source")
        .order_by("batch_id", "row_number", "id")
    )
    if _org_action_allowed(
        user, action="ingestion_batch.create", resource_type="ingestion_batch"
    ) or _org_action_allowed(user, action="mapping.resolve", resource_type="ingestion_batch"):
        return qs
    return qs.none()


def visible_product_public_ids_for_export(user: User) -> set[UUID] | None:
    """Return product public_ids visible for export, or None when org-wide export is allowed."""

    if _org_action_allowed(
        user,
        action="operating_detail.export",
        resource_type="operating_fact",
        sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
    ):
        return None

    product_ids = _assigned_product_ids(user)
    if not product_ids:
        return set()
    return set(
        ProductAsset.objects.filter(
            organization_id=user.organization_id, id__in=product_ids
        ).values_list("public_id", flat=True)
    )


def user_max_data_level(user: User) -> str:
    """Highest max_data_level from role permissions and monitoring assignments."""

    from django.db.models import Q
    from django.utils import timezone

    from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment

    now = timezone.now()
    levels: list[str] = []
    assignments = (
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=now,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
        .prefetch_related("role__permissions")
    )
    for assignment in assignments:
        for permission in assignment.role.permissions.all():
            levels.append(permission.max_data_level)
    for row in resolve_effective_assignments(user=user, organization_id=user.organization_id):
        levels.append(row.max_data_level)
    if not levels:
        return DataSensitivityLevel.PUBLIC_SUMMARY
    return max(levels, key=lambda level: LEVEL_RANK.get(level, 0))
