"""Build authorization subjects from persisted role assignments."""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from apps.authorization.context import AuthorizationSubject
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment
from apps.identity.models.user import User


def subject_for(user: User) -> AuthorizationSubject:
    now = timezone.now()
    role_codes = frozenset(
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=now,
        )
        .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gt=now))
        .values_list("role__role_code", flat=True)
    )
    return AuthorizationSubject(user=user, role_codes=role_codes)
