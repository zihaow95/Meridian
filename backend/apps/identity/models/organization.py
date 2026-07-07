"""Organization aggregate root."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import PublicIdModel


class OrganizationStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class Organization(PublicIdModel):
    name = models.CharField(max_length=255)
    status = models.CharField(
        max_length=16,
        choices=OrganizationStatus.choices,
        default=OrganizationStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "identity_organization"

    def __str__(self) -> str:
        return self.name
