"""Eight-step authorization engine with default deny."""

from __future__ import annotations

from django.db.models import Q

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import (
    LEVEL_RANK,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RoleStatus,
    RoleType,
)
from apps.authorization.policies.identity_provider import identity_registry
from apps.identity.models.user import UserStatus


def _level_covers(granted: str, required: str) -> bool:
    return LEVEL_RANK.get(granted, 0) >= LEVEL_RANK.get(required, 0)


def _assignment_covers_scope(
    *,
    scope_type: str,
    scope_id: int | None,
    resource: ResourceDescriptor,
    context: AuthorizationContext,
) -> bool:
    if scope_type == ScopeType.ORGANIZATION:
        return True
    if scope_type == ScopeType.DEPARTMENT:
        if scope_id is None:
            return False
        return scope_id in resource.scope_department_ids or scope_id in context.department_ids
    if scope_type == ScopeType.PRODUCT_SET:
        product_set_id = resource.metadata.get("product_set_id")
        return product_set_id is not None and scope_id == product_set_id
    return False


def _platform_role_blocked(role: Role, action: str, resource: ResourceDescriptor) -> bool:
    if role.role_type != RoleType.PLATFORM:
        return False
    if resource.sensitivity_level == DataSensitivityLevel.HIGHLY_SENSITIVE and action.startswith(
        "product."
    ):
        return True
    return False


def authorize(
    subject: AuthorizationSubject,
    *,
    action: str,
    resource: ResourceDescriptor,
    context: AuthorizationContext,
) -> AuthorizationDecision:
    user = subject.user

    if user.status != UserStatus.ACTIVE:
        return AuthorizationDecision(allowed=False, reason_code="USER_NOT_ACTIVE")

    if user.organization_id != resource.organization_id:
        return AuthorizationDecision(allowed=False, reason_code="ORGANIZATION_MISMATCH")

    if not PermissionAction.objects.filter(action_code=action).exists():
        object_identities = identity_registry.resolve(
            subject=subject, resource=resource, context=context
        )
        if action not in {identity.action_code for identity in object_identities}:
            return AuthorizationDecision(allowed=False, reason_code="UNKNOWN_ACTION")

    active_assignments = (
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=context.as_of,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=context.as_of))
        .select_related("role")
        .prefetch_related("role__permissions__action")
    )

    for assignment in active_assignments:
        role = assignment.role
        if role.status != RoleStatus.ACTIVE:
            continue
        if _platform_role_blocked(role, action, resource):
            continue
        for permission in role.permissions.all():
            if permission.action.action_code != action:
                continue
            if not _level_covers(permission.max_data_level, resource.sensitivity_level):
                continue
            if permission.requires_object_scope and not _assignment_covers_scope(
                scope_type=assignment.scope_type,
                scope_id=assignment.scope_id,
                resource=resource,
                context=context,
            ):
                continue
            return AuthorizationDecision(allowed=True, reason_code="ALLOWED")

    object_identities = identity_registry.resolve(
        subject=subject, resource=resource, context=context
    )
    if any(identity.action_code == action for identity in object_identities):
        return AuthorizationDecision(allowed=True, reason_code="ALLOWED")

    return AuthorizationDecision(allowed=False, reason_code="NO_ALLOWING_POLICY")
