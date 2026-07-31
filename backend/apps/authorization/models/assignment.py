"""Role assignment with scoped effective intervals."""

from __future__ import annotations

from django.db import models

from apps.platform.api.errors import ValidationFailedError
from apps.platform.models.base import PublicIdModel


class ScopeType(models.TextChoices):
    ORGANIZATION = "ORGANIZATION", "Organization"
    DEPARTMENT = "DEPARTMENT", "Department"
    PRODUCT_SET = "PRODUCT_SET", "Product set"


class AssignmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


def resolve_scope_id(
    *,
    scope_type: str,
    scope_id: int | None,
    organization_id: int,
) -> int:
    """Normalize scope identifiers so MySQL unique indexes never see NULL."""

    if scope_type == ScopeType.ORGANIZATION:
        return organization_id if scope_id is None else scope_id
    if scope_id is None:
        raise ValidationFailedError(message=f"scope_id is required for scope_type={scope_type}.")
    return scope_id


def build_scope_key(*, scope_type: str, scope_id: int) -> str:
    return f"{scope_type}:{scope_id}"


class RoleAssignment(PublicIdModel):
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    role = models.ForeignKey(
        "authorization.Role",
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    scope_type = models.CharField(max_length=32, choices=ScopeType.choices)
    scope_id = models.BigIntegerField()
    scope_key = models.CharField(max_length=64)
    effective_from = models.DateTimeField()
    effective_to = models.DateTimeField(null=True, blank=True)
    configured_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="configured_role_assignments",
    )
    approval_reference = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=16,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.ACTIVE,
    )
    # MySQL-compatible uniqueness for the single ACTIVE open assignment per scope.
    # Null when inactive/closed so historical rows do not collide.
    active_slot = models.PositiveSmallIntegerField(null=True, blank=True, default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "authorization_role_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role", "scope_type", "scope_key", "active_slot"],
                name="authorization_role_assignment_scope_key_slot_uniq",
            ),
        ]
