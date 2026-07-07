"""Internal user aggregate."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models

from apps.platform.models.base import PublicIdModel

if TYPE_CHECKING:
    from apps.identity.models.organization import Organization


class UserStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACTIVE = "ACTIVE", "Active"
    DISABLED = "DISABLED", "Disabled"
    DEPARTED = "DEPARTED", "Departed"


class UserManager(BaseUserManager["User"]):
    def create_user(
        self,
        *,
        organization: Organization,
        display_name: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        if not display_name:
            raise ValueError("display_name is required")
        user = self.model(organization=organization, display_name=display_name, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PublicIdModel):
    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="users",
    )
    employee_no = models.CharField(max_length=64, blank=True, default="")
    display_name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=UserStatus.choices,
        default=UserStatus.PENDING,
    )
    primary_department = models.ForeignKey(
        "identity.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="primary_users",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    disabled_at = models.DateTimeField(null=True, blank=True)
    departed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    login_key = models.CharField(max_length=64, unique=True, editable=False)

    objects = UserManager()

    USERNAME_FIELD = "login_key"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "identity_user"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "employee_no"],
                condition=~models.Q(employee_no=""),
                name="identity_user_org_employee_no_uniq",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self.login_key:
            self.login_key = uuid.uuid4().hex
        super().save(*args, **kwargs)

    @property
    def is_active(self) -> bool:  # type: ignore[override]
        return self.status == UserStatus.ACTIVE

    def __str__(self) -> str:
        return self.display_name
