"""External system bindings and operating data sources."""

from __future__ import annotations

from typing import Any

from django.db import models

from apps.authorization.models.role import DataSensitivityLevel
from apps.platform.models.base import OrganizationOwnedModel


class BindingStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "Active"
    INACTIVE = "INACTIVE", "Inactive"


class DataSourceType(models.TextChoices):
    API = "API", "API"
    FILE = "FILE", "File"
    MANUAL = "MANUAL", "Manual"


class DataSourceStatus(models.TextChoices):
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


class DataSource(OrganizationOwnedModel):
    source_code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    source_type = models.CharField(max_length=16, choices=DataSourceType.choices)
    owner_department = models.ForeignKey(
        "identity.Department",
        on_delete=models.PROTECT,
        related_name="owned_data_sources",
    )
    sensitivity_level = models.CharField(
        max_length=32,
        choices=DataSensitivityLevel.choices,
        default=DataSensitivityLevel.INTERNAL,
    )
    status = models.CharField(
        max_length=16,
        choices=DataSourceStatus.choices,
        default=DataSourceStatus.ACTIVE,
    )
    configuration_version = models.ForeignKey(
        "configuration.ConfigurationVersion",
        on_delete=models.PROTECT,
        related_name="operating_data_sources",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "integrations_data_source"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "source_code"],
                name="integrations_data_source_org_code_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "source_type"]),
        ]

    def __str__(self) -> str:
        return self.source_code

    def locked_source_priority(self) -> int:
        content = self.configuration_version.content_json or {}
        return int(content["source_priority"])

    def locked_mapping_rules(self) -> list[dict[str, Any]]:
        content = self.configuration_version.content_json or {}
        rules = content.get("mapping_rules") or []
        return list(rules)
