"""Helpers for building audit payloads from command actors."""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment
from apps.identity.models.user import User


def acting_roles_snapshot(user: User) -> list[str]:
    now = timezone.now()
    return list(
        RoleAssignment.objects.filter(
            user=user,
            status=AssignmentStatus.ACTIVE,
            effective_from__lte=now,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=now))
        .values_list("role__role_code", flat=True)
        .distinct()
    )
