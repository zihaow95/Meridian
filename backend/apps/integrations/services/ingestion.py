"""Create, validate, retry, and lock operating ingestion batches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.models import DocumentVersion
from apps.identity.models.user import User
from apps.integrations.models import (
    DataSource,
    IngestionBatch,
    IngestionBatchStatus,
    IngestionRow,
    IngestionRowStatus,
)
from apps.integrations.services.data_sources import assert_active_for_ingestion
from apps.integrations.services.parsers import (
    assert_controlled_active_document_version,
    parse_rows_from_document_version,
)
from apps.integrations.services.validation import apply_mapping, validate_batch_rows
from apps.operations.errors import (
    IngestionBatchDuplicate,
    OperatingDataMappingRequired,
    OperatingDataStructureInvalid,
    OperatingUnitMismatch,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext


def _authorize(actor: User, action: str, *, public_id: UUID | None = None) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type="ingestion_batch",
            public_id=public_id,
            organization_id=actor.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _get_source(*, organization_id: int, source_public_id: UUID) -> DataSource:
    source = (
        DataSource.objects.select_related("configuration_version")
        .filter(organization_id=organization_id, public_id=source_public_id)
        .first()
    )
    if source is None:
        raise ValidationFailedError(message="Data source not found.")
    return source


@dataclass
class CreateIngestionBatch:
    context: CommandContext
    source_public_id: UUID
    batch_key: str
    source_type: str
    rows: list[dict[str, Any]] | None = None
    input_file_version_public_id: UUID | None = None

    def execute(self) -> IngestionBatch:
        actor = self.context.actor
        with transaction.atomic():
            _authorize(actor, "ingestion_batch.create")
            source = _get_source(
                organization_id=actor.organization_id,
                source_public_id=self.source_public_id,
            )
            assert_active_for_ingestion(source)
            if self.source_type != source.source_type:
                raise ValidationFailedError(message="source_type must match data source.")

            existing = IngestionBatch.objects.filter(
                source=source, batch_key=self.batch_key
            ).first()
            if existing is not None:
                if existing.status in {
                    IngestionBatchStatus.SUCCESS,
                    IngestionBatchStatus.PARTIAL_SUCCESS,
                }:
                    # Idempotent retries reuse the batch key before completion; resubmitting
                    # a batch key that already finished is a genuine duplicate submission.
                    raise IngestionBatchDuplicate(
                        details={"batch_public_id": str(existing.public_id)}
                    )
                return existing

            file_version = None
            row_payloads: list[dict[str, Any]]
            if self.input_file_version_public_id is not None:
                file_version = (
                    DocumentVersion.objects.select_related("file_object")
                    .filter(
                        organization_id=actor.organization_id,
                        public_id=self.input_file_version_public_id,
                    )
                    .first()
                )
                if file_version is None:
                    raise ValidationFailedError(message="Input document version not found.")
                assert_controlled_active_document_version(file_version)
                row_payloads = parse_rows_from_document_version(file_version)
            else:
                row_payloads = list(self.rows or [])
                if not row_payloads:
                    raise OperatingDataStructureInvalid(
                        message="rows or input_file_version is required."
                    )

            batch = IngestionBatch.objects.create(
                organization_id=actor.organization_id,
                source=source,
                batch_key=self.batch_key,
                source_type=self.source_type,
                input_file_version=file_version,
                status=IngestionBatchStatus.RECEIVED,
                total_count=len(row_payloads),
                created_by=actor,
            )
            mapping_rules = source.locked_mapping_rules()
            for index, raw in enumerate(row_payloads, start=1):
                mapped = apply_mapping(raw, mapping_rules)
                IngestionRow.objects.create(
                    organization_id=actor.organization_id,
                    batch=batch,
                    row_number=index,
                    external_record_key=str(mapped.get("external_record_key") or "").strip(),
                    raw_payload=raw,
                    sku_code=str(mapped.get("sku_code") or "").strip(),
                    channel_code=str(mapped.get("channel_code") or "").strip(),
                    metric_code=str(mapped.get("metric_code") or "").strip(),
                    period_granularity=str(mapped.get("period_granularity") or "").strip(),
                    unit=str(mapped.get("unit") or "").strip(),
                    currency=str(mapped.get("currency") or "").strip(),
                    text_value=str(mapped.get("text_value") or ""),
                    status=IngestionRowStatus.VALID,
                )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="ingestion_batch.create",
                    resource_type="ingestion_batch",
                    resource_public_id=batch.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    before_summary={},
                    after_summary={
                        "batch_key": batch.batch_key,
                        "total_count": batch.total_count,
                    },
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            return batch


@dataclass
class ValidateIngestionBatch:
    context: CommandContext
    batch_public_id: UUID

    def execute(self) -> IngestionBatch:
        actor = self.context.actor
        with transaction.atomic():
            _authorize(actor, "ingestion_batch.create", public_id=self.batch_public_id)
            batch = (
                IngestionBatch.objects.select_for_update()
                .select_related("source", "source__configuration_version")
                .filter(organization_id=actor.organization_id, public_id=self.batch_public_id)
                .first()
            )
            if batch is None:
                raise ValidationFailedError(message="Ingestion batch not found.")
            if batch.status not in {
                IngestionBatchStatus.RECEIVED,
                IngestionBatchStatus.FAILED,
                IngestionBatchStatus.READY,
            }:
                raise ValidationFailedError(message="Batch cannot be validated in current status.")

            batch.status = IngestionBatchStatus.VALIDATING
            batch.save(update_fields=["status", "updated_at"])
            validate_batch_rows(batch)
            batch.status = IngestionBatchStatus.READY
            batch.save(
                update_fields=[
                    "status",
                    "total_count",
                    "success_count",
                    "warning_count",
                    "error_count",
                    "skipped_count",
                    "updated_at",
                ]
            )
            return batch


@dataclass
class RetryIngestionBatch:
    context: CommandContext
    batch_public_id: UUID

    def execute(self) -> IngestionBatch:
        actor = self.context.actor
        with transaction.atomic():
            _authorize(actor, "ingestion_batch.retry", public_id=self.batch_public_id)
            batch = (
                IngestionBatch.objects.select_for_update()
                .filter(organization_id=actor.organization_id, public_id=self.batch_public_id)
                .first()
            )
            if batch is None:
                raise ValidationFailedError(message="Ingestion batch not found.")
            if batch.status not in {
                IngestionBatchStatus.FAILED,
                IngestionBatchStatus.PARTIAL_SUCCESS,
                IngestionBatchStatus.READY,
            }:
                raise ValidationFailedError(message="Batch cannot be retried in current status.")
            # Re-validate only; never mutate previously imported OperatingFact rows.
            return ValidateIngestionBatch(
                context=self.context,
                batch_public_id=self.batch_public_id,
            ).execute()


@dataclass
class ResolveIngestionMapping:
    context: CommandContext
    batch_public_id: UUID
    row_public_id: UUID
    sku_public_id: UUID
    channel_public_id: UUID

    def execute(self) -> IngestionRow:
        actor = self.context.actor
        with transaction.atomic():
            _authorize(actor, "mapping.resolve", public_id=self.batch_public_id)
            row = (
                IngestionRow.objects.select_for_update()
                .select_related("batch")
                .filter(
                    organization_id=actor.organization_id,
                    public_id=self.row_public_id,
                    batch__public_id=self.batch_public_id,
                )
                .first()
            )
            if row is None:
                raise ValidationFailedError(message="Ingestion row not found.")
            from apps.operations.models import MetricDefinitionStatus, MetricDefinitionVersion
            from apps.products.models import SKU, ChannelConfiguration

            sku = SKU.objects.filter(
                organization_id=actor.organization_id, public_id=self.sku_public_id
            ).first()
            channel = ChannelConfiguration.objects.filter(
                organization_id=actor.organization_id, public_id=self.channel_public_id
            ).first()
            if sku is None or channel is None or channel.sku_id != sku.id:
                raise OperatingDataMappingRequired(message="Invalid SKU/channel mapping.")

            metric = (
                MetricDefinitionVersion.objects.filter(
                    organization_id=actor.organization_id,
                    metric_code=row.metric_code,
                    status=MetricDefinitionStatus.PUBLISHED,
                )
                .order_by("-version_number")
                .first()
                if row.metric_code
                else None
            )
            if metric is not None and (
                (metric.unit and row.unit and metric.unit != row.unit)
                or (metric.currency and row.currency and metric.currency != row.currency)
            ):
                raise OperatingUnitMismatch(
                    message=(
                        f"Row unit/currency ({row.unit}/{row.currency}) does not match "
                        f"published metric definition ({metric.unit}/{metric.currency})."
                    )
                )

            row.sku = sku
            row.channel = channel
            row.sku_code = sku.sku_code
            row.channel_code = channel.channel_code
            row.metric_definition = metric
            row.status = IngestionRowStatus.VALID
            row.error_code = ""
            row.error_message = ""
            row.save()
            return row


def lock_batch_for_confirm(*, organization_id: int, batch_public_id: UUID) -> IngestionBatch:
    batch = (
        IngestionBatch.objects.select_for_update()
        .select_related("source", "source__configuration_version")
        .filter(organization_id=organization_id, public_id=batch_public_id)
        .first()
    )
    if batch is None:
        raise ValidationFailedError(message="Ingestion batch not found.")
    return batch


def mark_rows_imported(row_ids: list[int]) -> None:
    IngestionRow.objects.filter(id__in=row_ids).update(
        status=IngestionRowStatus.IMPORTED,
        updated_at=timezone.now(),
    )


def mark_rows_skipped(row_ids: list[int]) -> None:
    IngestionRow.objects.filter(id__in=row_ids).update(
        status=IngestionRowStatus.SKIPPED,
        updated_at=timezone.now(),
    )


def complete_batch_confirm(
    *,
    batch: IngestionBatch,
    status: str,
    added_count: int,
    revision_count: int,
    skipped_count: int,
    error_count: int,
    warning_count: int,
    success_count: int,
    idempotency_key: str,
) -> IngestionBatch:
    batch.status = status
    batch.added_count = added_count
    batch.revision_count = revision_count
    batch.skipped_count = skipped_count
    batch.error_count = error_count
    batch.warning_count = warning_count
    batch.success_count = success_count
    batch.confirm_idempotency_key = idempotency_key
    batch.completed_at = timezone.now()
    if batch.started_at is None:
        batch.started_at = batch.completed_at
    batch.save(
        update_fields=[
            "status",
            "added_count",
            "revision_count",
            "skipped_count",
            "error_count",
            "warning_count",
            "success_count",
            "confirm_idempotency_key",
            "started_at",
            "completed_at",
            "updated_at",
        ]
    )
    return batch
