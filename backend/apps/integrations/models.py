"""External system bindings to internal business objects."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class BindingStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class ExternalBinding(OrganizationOwnedModel):
    source_system = models.CharField(max_length=40)
    object_type = models.CharField(max_length=40)
    external_id = models.CharField(max_length=120)
    internal_object_type = models.CharField(max_length=40)
    internal_object_id = models.BigIntegerField()
    source_timestamp = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    binding_status = models.CharField(
        max_length=16,
        choices=BindingStatus.choices,
        default=BindingStatus.ACTIVE,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "integrations_external_binding"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source_system", "object_type", "external_id"],
                name="integrations_external_binding_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["internal_object_type", "internal_object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_system}:{self.object_type}:{self.external_id}"
