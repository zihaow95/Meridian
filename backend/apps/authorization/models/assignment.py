"""Role assignment with scoped effective intervals."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import PublicIdModel


class ScopeType(models.TextChoices):
    ORGANIZATION = "ORGANIZATION", "Organization"
    DEPARTMENT = "DEPARTMENT", "Department"
    PRODUCT_SET = "PRODUCT_SET", "Product set"


class AssignmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


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
    scope_id = models.BigIntegerField(null=True, blank=True)
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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "authorization_role_assignment"
