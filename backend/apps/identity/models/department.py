"""Department hierarchy and user membership."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class DepartmentStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class Department(OrganizationOwnedModel):
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    department_code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=DepartmentStatus.choices,
        default=DepartmentStatus.ACTIVE,
    )
    external_dingtalk_id = models.CharField(max_length=128, blank=True, default="")
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "identity_department"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "department_code"],
                name="identity_department_org_code_uniq",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class UserDepartment(models.Model):
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="department_memberships",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="user_memberships",
    )
    is_primary = models.BooleanField(default=False)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "identity_user_department"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "department", "valid_from"],
                name="identity_user_department_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}:{self.department_id}"
