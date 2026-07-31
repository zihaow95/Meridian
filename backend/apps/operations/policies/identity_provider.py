"""Object identity from effective monitoring assignments."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ObjectIdentity,
    ResourceDescriptor,
)
from apps.authorization.models.role import LEVEL_RANK
from apps.authorization.policies.identity_provider import identity_registry
from apps.identity.models.user import User
from apps.operations.models import (
    MonitoringAssignment,
    MonitoringAssignmentStatus,
    MonitoringScopeType,
)
from apps.products.models import SKU, ChannelConfiguration, ProductAsset

SUPERVISOR_ACTIONS: frozenset[str] = frozenset(
    {
        "operating_fact.read",
        "risk_signal.read",
        "risk_signal.close",
        "risk_signal.escalate",
        "operating_issue.create",
        "operating_issue.analyze",
        "operating_issue.close",
        "iteration_proposal.convert",
        "manual_effective_value.create",
        "manual_effective_value.modify",
        "manual_effective_value.revoke",
    }
)


def resolve_effective_assignments(
    *,
    user: User,
    organization_id: int,
    as_of: datetime | None = None,
) -> list[MonitoringAssignment]:
    moment = as_of or timezone.now()
    rows = list(
        MonitoringAssignment.objects.filter(
            organization_id=organization_id,
            supervisor=user,
            status=MonitoringAssignmentStatus.ACTIVE,
            effective_from__lte=moment,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=moment))
        .select_related("product", "sku", "channel")
    )
    return [row for row in rows if row.is_effective(as_of=moment)]


def _level_covers(granted: str, required: str) -> bool:
    return LEVEL_RANK.get(granted, 0) >= LEVEL_RANK.get(required, 0)


def _assignment_covers_resource(
    assignment: MonitoringAssignment,
    *,
    product: ProductAsset | None,
    sku: SKU | None,
    channel: ChannelConfiguration | None,
) -> bool:
    if product is None:
        return False
    if assignment.product_id != product.id:
        return False
    if assignment.scope_type == MonitoringScopeType.PRODUCT:
        return True
    if assignment.scope_type == MonitoringScopeType.SKU:
        return sku is not None and assignment.sku_id == sku.id
    if assignment.scope_type == MonitoringScopeType.SKU_CHANNEL:
        return (
            sku is not None
            and channel is not None
            and assignment.sku_id == sku.id
            and assignment.channel_id == channel.id
        )
    return False


def _resolve_product_sku_channel(
    resource: ResourceDescriptor,
) -> tuple[ProductAsset | None, SKU | None, ChannelConfiguration | None]:
    metadata = resource.metadata or {}
    product = None
    sku = None
    channel = None

    product_public_id = metadata.get("product_public_id")
    if product_public_id is None and resource.resource_type in {
        "operating_fact",
        "product",
    }:
        product_public_id = str(resource.public_id) if resource.public_id else None
    if product_public_id is not None:
        product = ProductAsset.objects.filter(
            public_id=product_public_id,
            organization_id=resource.organization_id,
        ).first()

    sku_public_id = metadata.get("sku_public_id")
    if sku_public_id is not None:
        sku = SKU.objects.filter(
            public_id=sku_public_id,
            organization_id=resource.organization_id,
        ).first()

    channel_public_id = metadata.get("channel_public_id")
    if channel_public_id is not None:
        channel = ChannelConfiguration.objects.filter(
            public_id=channel_public_id,
            organization_id=resource.organization_id,
        ).first()
    return product, sku, channel


class OperatingFactIdentityProvider:
    resource_type = "operating_fact"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        assignments = resolve_effective_assignments(
            user=subject.user,
            organization_id=resource.organization_id,
            as_of=context.as_of,
        )
        if not assignments:
            return ()

        product, sku, channel = _resolve_product_sku_channel(resource)
        granted: set[str] = set()
        for assignment in assignments:
            if not _assignment_covers_resource(
                assignment, product=product, sku=sku, channel=channel
            ):
                continue
            if not _level_covers(assignment.max_data_level, resource.sensitivity_level):
                continue
            granted.update(SUPERVISOR_ACTIONS)

        return tuple(ObjectIdentity(action_code=action, resource=resource) for action in granted)


class RiskSignalIdentityProvider:
    resource_type = "risk_signal"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        assignments = resolve_effective_assignments(
            user=subject.user,
            organization_id=resource.organization_id,
            as_of=context.as_of,
        )
        if not assignments:
            return ()

        product, sku, channel = _resolve_product_sku_channel(resource)
        granted: set[str] = set()
        for assignment in assignments:
            if not _assignment_covers_resource(
                assignment, product=product, sku=sku, channel=channel
            ):
                continue
            if not _level_covers(assignment.max_data_level, resource.sensitivity_level):
                continue
            granted.update({"risk_signal.read", "risk_signal.close", "risk_signal.escalate"})

        return tuple(ObjectIdentity(action_code=action, resource=resource) for action in granted)


class OperatingIssueIdentityProvider:
    resource_type = "operating_issue"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        assignments = resolve_effective_assignments(
            user=subject.user,
            organization_id=resource.organization_id,
            as_of=context.as_of,
        )
        if not assignments:
            return ()

        product, sku, channel = _resolve_product_sku_channel(resource)
        granted: set[str] = set()
        for assignment in assignments:
            if not _assignment_covers_resource(
                assignment, product=product, sku=sku, channel=channel
            ):
                continue
            if not _level_covers(assignment.max_data_level, resource.sensitivity_level):
                continue
            granted.update(
                {
                    "operating_issue.create",
                    "operating_issue.analyze",
                    "operating_issue.close",
                    "iteration_proposal.convert",
                }
            )

        return tuple(ObjectIdentity(action_code=action, resource=resource) for action in granted)


class MonitoringScopeIdentityProvider:
    resource_type = "monitoring_scope"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        del context
        from apps.operations.models import MonitoringScope

        if resource.public_id is None:
            return ()
        scope = MonitoringScope.objects.filter(
            public_id=resource.public_id,
            organization_id=resource.organization_id,
        ).first()
        if scope is None:
            return ()
        if scope.owner_id == subject.user.id:
            return (ObjectIdentity(action_code="monitoring_scope.manage", resource=resource),)
        return ()


def register_providers() -> None:
    identity_registry.register(OperatingFactIdentityProvider())
    identity_registry.register(RiskSignalIdentityProvider())
    identity_registry.register(OperatingIssueIdentityProvider())
    identity_registry.register(MonitoringScopeIdentityProvider())
