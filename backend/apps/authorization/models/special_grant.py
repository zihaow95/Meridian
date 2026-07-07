"""Time-limited special authorization grants."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import PublicIdModel


class SpecialGrantStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"
    REVOKED = "REVOKED", "Revoked"


class SpecialGrant(PublicIdModel):
    grantee = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="special_grants",
    )
    grantor = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="granted_special_grants",
    )
    resource_type = models.CharField(max_length=64)
    resource_public_id = models.UUIDField(null=True, blank=True)
    actions = models.JSONField(default=list)
    max_sensitivity_level = models.CharField(max_length=32)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=SpecialGrantStatus.choices,
        default=SpecialGrantStatus.PENDING,
    )
    purpose = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "authorization_special_grant"

    def __str__(self) -> str:
        return f"{self.resource_type}:{self.public_id}"
