"""Database-layer visibility filters for authorized list queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.authorization.context import AuthorizationContext, AuthorizationSubject
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import DataSensitivityLevel, RoleStatus, RoleType
from apps.identity.models.user import User


@dataclass(frozen=True)
class VisibleResourceFilter:
    user: User
    action: str
    organization_id: int

    def build_queryset_filter(self, *, model: type[Any], resource_type: str) -> Q:
        context = AuthorizationContext.current()
        subject = self._subject()
        base = Q(organization_id=self.organization_id)

        if not subject.role_codes:
            return base & Q(pk__in=[])

        allowed_scope = Q()
        now = context.as_of
        assignments = (
            RoleAssignment.objects.filter(
                user=self.user,
                status=AssignmentStatus.ACTIVE,
                effective_from__lte=now,
                role__status=RoleStatus.ACTIVE,
                role__permissions__action__action_code=self.action,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
            .select_related("role")
        )

        for assignment in assignments.distinct():
            if assignment.role.role_type == RoleType.PLATFORM and self.action.startswith(
                "product."
            ):
                continue
            if assignment.scope_type == ScopeType.ORGANIZATION:
                allowed_scope |= Q(pk__isnull=False)
            elif assignment.scope_type == ScopeType.DEPARTMENT and assignment.scope_id is not None:
                allowed_scope |= Q(scope_department_id=assignment.scope_id)

        if allowed_scope == Q():
            return base & Q(pk__in=[])

        return base & allowed_scope

    def project_fields(self, fields: dict[str, Any], *, sensitivity_level: str) -> dict[str, Any]:
        if sensitivity_level == DataSensitivityLevel.HIGHLY_SENSITIVE:
            return {key: value for key, value in fields.items() if not key.startswith("formula_")}
        return fields

    def _subject(self) -> AuthorizationSubject:
        now = timezone.now()
        role_codes = frozenset(
            RoleAssignment.objects.filter(
                user=self.user,
                status=AssignmentStatus.ACTIVE,
                effective_from__lte=now,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
            .values_list("role__role_code", flat=True)
        )
        return AuthorizationSubject(user=self.user, role_codes=role_codes)


def apply_visible_filter(
    queryset: QuerySet[Any], resource_filter: VisibleResourceFilter, *, resource_type: str
) -> QuerySet[Any]:
    condition = resource_filter.build_queryset_filter(
        model=queryset.model, resource_type=resource_type
    )
    return queryset.filter(condition)
