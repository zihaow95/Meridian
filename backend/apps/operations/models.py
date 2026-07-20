"""Minimal operations handover models for phase 4 (monitoring scope only)."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class MonitoringScopeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    CLOSED = "CLOSED", "Closed"


class MonitoringScope(OrganizationOwnedModel):
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="monitoring_scopes",
    )
    product_version = models.ForeignKey(
        "products.ProductVersion",
        on_delete=models.PROTECT,
        related_name="monitoring_scopes",
    )
    owner = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="owned_monitoring_scopes",
    )
    effective_at = models.DateTimeField()
    status = models.CharField(
        max_length=16,
        choices=MonitoringScopeStatus.choices,
        default=MonitoringScopeStatus.ACTIVE,
    )
    source_decision_public_id = models.UUIDField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "operations_monitoring_scope"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "source_decision_public_id"],
                name="operations_monitoring_scope_project_decision_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.project_id}:{self.product_version_id}"
