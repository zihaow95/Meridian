"""RBAC role and permission catalog."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import PublicIdModel


class RoleType(models.TextChoices):
    PLATFORM = "PLATFORM", "Platform"
    BUSINESS = "BUSINESS", "Business"


class RoleStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class ActionCategory(models.TextChoices):
    READ = "READ", "Read"
    WRITE = "WRITE", "Write"
    DECIDE = "DECIDE", "Decide"
    ADMIN = "ADMIN", "Admin"
    EXPORT = "EXPORT", "Export"


class DataSensitivityLevel(models.TextChoices):
    PUBLIC_SUMMARY = "PUBLIC_SUMMARY", "Public summary"
    INTERNAL = "INTERNAL", "Internal"
    PROJECT_CONTROLLED = "PROJECT_CONTROLLED", "Project controlled"
    SENSITIVE_CONTROLLED = "SENSITIVE_CONTROLLED", "Sensitive controlled"
    HIGHLY_SENSITIVE = "HIGHLY_SENSITIVE", "Highly sensitive"


LEVEL_RANK: dict[str, int] = {
    DataSensitivityLevel.PUBLIC_SUMMARY: 1,
    DataSensitivityLevel.INTERNAL: 2,
    DataSensitivityLevel.PROJECT_CONTROLLED: 3,
    DataSensitivityLevel.SENSITIVE_CONTROLLED: 4,
    DataSensitivityLevel.HIGHLY_SENSITIVE: 5,
}


class Role(PublicIdModel):
    role_code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    role_type = models.CharField(max_length=16, choices=RoleType.choices)
    is_critical = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=RoleStatus.choices,
        default=RoleStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "authorization_role"

    def __str__(self) -> str:
        return self.role_code


class PermissionAction(models.Model):
    action_code = models.CharField(max_length=128, unique=True)
    resource_type = models.CharField(max_length=64)
    action_category = models.CharField(max_length=16, choices=ActionCategory.choices)
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "authorization_permission_action"

    def __str__(self) -> str:
        return self.action_code


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="permissions")
    action = models.ForeignKey(
        PermissionAction, on_delete=models.PROTECT, related_name="role_permissions"
    )
    max_data_level = models.CharField(max_length=32, choices=DataSensitivityLevel.choices)
    requires_object_scope = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "authorization_role_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "action"], name="authorization_role_action_uniq"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.role_id}:{self.action_id}"
