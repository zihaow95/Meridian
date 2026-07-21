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

    def locked_reasonable_ranges(self) -> dict[str, Any]:
        content = self.configuration_version.content_json or {}
        ranges = content.get("reasonable_ranges") or {}
        return dict(ranges)


class IngestionBatchStatus(models.TextChoices):
    RECEIVED = "RECEIVED", "Received"
    VALIDATING = "VALIDATING", "Validating"
    READY = "READY", "Ready"
    IMPORTING = "IMPORTING", "Importing"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS", "Partial success"
    SUCCESS = "SUCCESS", "Success"
    FAILED = "FAILED", "Failed"


class IngestionRowStatus(models.TextChoices):
    VALID = "VALID", "Valid"
    WARNING = "WARNING", "Warning"
    ERROR = "ERROR", "Error"
    UNMAPPED = "UNMAPPED", "Unmapped"
    IMPORTED = "IMPORTED", "Imported"
    SKIPPED = "SKIPPED", "Skipped"


class IngestionBatch(OrganizationOwnedModel):
    source = models.ForeignKey(
        DataSource,
        on_delete=models.PROTECT,
        related_name="ingestion_batches",
    )
    batch_key = models.CharField(max_length=128)
    source_type = models.CharField(max_length=16, choices=DataSourceType.choices)
    input_file_version = models.ForeignKey(
        "documents.DocumentVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="operating_ingestion_batches",
    )
    business_period_from = models.DateField(null=True, blank=True)
    business_period_to = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=IngestionBatchStatus.choices,
        default=IngestionBatchStatus.RECEIVED,
    )
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    added_count = models.PositiveIntegerField(default=0)
    revision_count = models.PositiveIntegerField(default=0)
    confirm_idempotency_key = models.CharField(max_length=128, blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="created_ingestion_batches",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "integrations_ingestion_batch"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "batch_key"],
                name="integrations_ingestion_batch_source_key_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.source_id}:{self.batch_key}"


class IngestionRow(OrganizationOwnedModel):
    batch = models.ForeignKey(
        IngestionBatch,
        on_delete=models.CASCADE,
        related_name="rows",
    )
    row_number = models.PositiveIntegerField()
    external_record_key = models.CharField(max_length=128, blank=True, default="")
    raw_payload = models.JSONField(default=dict)
    sku_code = models.CharField(max_length=64, blank=True, default="")
    channel_code = models.CharField(max_length=64, blank=True, default="")
    metric_code = models.CharField(max_length=64, blank=True, default="")
    sku = models.ForeignKey(
        "products.SKU",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ingestion_rows",
    )
    channel = models.ForeignKey(
        "products.ChannelConfiguration",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ingestion_rows",
    )
    metric_definition = models.ForeignKey(
        "operations.MetricDefinitionVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="ingestion_rows",
    )
    period_granularity = models.CharField(max_length=12, blank=True, default="")
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    numeric_value = models.DecimalField(max_digits=24, decimal_places=6, null=True, blank=True)
    text_value = models.TextField(blank=True, default="")
    unit = models.CharField(max_length=32, blank=True, default="")
    currency = models.CharField(max_length=16, blank=True, default="")
    source_timestamp = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=IngestionRowStatus.choices,
        default=IngestionRowStatus.VALID,
    )
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    warning_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "integrations_ingestion_row"
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_number"],
                name="integrations_ingestion_row_batch_num_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["batch", "status"]),
            models.Index(fields=["batch", "external_record_key"]),
        ]

    def __str__(self) -> str:
        return f"{self.batch_id}:{self.row_number}"
