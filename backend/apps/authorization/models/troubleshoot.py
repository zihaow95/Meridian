"""Time-limited troubleshooting access grants."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import PublicIdModel


class TroubleshootAccessStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    EXPIRED = "EXPIRED", "Expired"
    CLOSED = "CLOSED", "Closed"


class TroubleshootAccess(PublicIdModel):
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="troubleshoot_accesses",
    )
    opened_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="opened_troubleshoot_accesses",
    )
    resource_type = models.CharField(max_length=64)
    resource_public_id = models.UUIDField(null=True, blank=True)
    actions = models.JSONField(default=list)
    max_sensitivity_level = models.CharField(max_length=32)
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=TroubleshootAccessStatus.choices,
        default=TroubleshootAccessStatus.ACTIVE,
    )
    purpose = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "authorization_troubleshoot_access"

    def __str__(self) -> str:
        return f"{self.resource_type}:{self.public_id}"
