"""Confirm validated ingestion batches into operating facts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.integrations.models import IngestionBatchStatus, IngestionRowStatus
from apps.integrations.services.ingestion import (
    complete_batch_confirm,
    lock_batch_for_confirm,
    mark_rows_imported,
    mark_rows_skipped,
)
from apps.operations.errors import UnconfirmedIngestionWarnings
from apps.operations.services.operating_facts import import_row_as_fact
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


@dataclass
class ConfirmBatchResult:
    public_id: UUID
    added_count: int
    revision_count: int
    skipped_count: int
    error_count: int
    warning_count: int


@dataclass
class ConfirmOperatingIngestionBatch:
    context: CommandContext
    batch_public_id: UUID
    idempotency_key: str
    confirm_warnings: bool = False

    def execute(self) -> ConfirmBatchResult:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="ingestion_batch.confirm",
                resource=ResourceDescriptor(
                    resource_type="ingestion_batch",
                    public_id=self.batch_public_id,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            batch = lock_batch_for_confirm(
                organization_id=actor.organization_id,
                batch_public_id=self.batch_public_id,
            )
            if batch.status in {
                IngestionBatchStatus.SUCCESS,
                IngestionBatchStatus.PARTIAL_SUCCESS,
            }:
                return ConfirmBatchResult(
                    public_id=batch.public_id,
                    added_count=batch.added_count,
                    revision_count=batch.revision_count,
                    skipped_count=batch.skipped_count,
                    error_count=batch.error_count,
                    warning_count=batch.warning_count,
                )
            if batch.status != IngestionBatchStatus.READY:
                raise ValidationFailedError(message="Batch must be READY before confirm.")

            rows = list(batch.rows.select_for_update().order_by("row_number"))
            warning_rows = [row for row in rows if row.status == IngestionRowStatus.WARNING]
            if warning_rows and not self.confirm_warnings:
                raise UnconfirmedIngestionWarnings()

            batch.status = IngestionBatchStatus.IMPORTING
            batch.started_at = now
            batch.save(update_fields=["status", "started_at", "updated_at"])

            added = 0
            revisions = 0
            skipped = 0
            errors = 0
            warnings = 0
            imported_ids: list[int] = []
            skipped_ids: list[int] = []
            imported_any = False

            for row in rows:
                if row.status == IngestionRowStatus.WARNING:
                    warnings += 1
                outcome, fact = import_row_as_fact(batch=batch, row=row)
                if outcome == "added":
                    added += 1
                    imported_ids.append(row.id)
                    imported_any = True
                elif outcome == "revision":
                    revisions += 1
                    imported_ids.append(row.id)
                    imported_any = True
                elif outcome == "skipped":
                    skipped += 1
                    if row.status not in {
                        IngestionRowStatus.ERROR,
                        IngestionRowStatus.UNMAPPED,
                    }:
                        skipped_ids.append(row.id)
                    if row.status in {IngestionRowStatus.ERROR, IngestionRowStatus.UNMAPPED}:
                        errors += 1
                else:
                    errors += 1
                    skipped += 1
                    if row.status not in {
                        IngestionRowStatus.ERROR,
                        IngestionRowStatus.UNMAPPED,
                    }:
                        skipped_ids.append(row.id)
                del fact

            mark_rows_imported(imported_ids)
            mark_rows_skipped(skipped_ids)

            if imported_any and (errors > 0 or skipped > 0):
                status = IngestionBatchStatus.PARTIAL_SUCCESS
            elif imported_any:
                status = IngestionBatchStatus.SUCCESS
            else:
                status = IngestionBatchStatus.FAILED

            complete_batch_confirm(
                batch=batch,
                status=status,
                added_count=added,
                revision_count=revisions,
                skipped_count=skipped,
                error_count=errors,
                warning_count=warnings,
                success_count=added + revisions,
                idempotency_key=self.idempotency_key,
            )

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="ingestion_batch.confirm",
                    resource_type="ingestion_batch",
                    resource_public_id=batch.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    before_summary={},
                    after_summary={
                        "added_count": added,
                        "revision_count": revisions,
                        "status": status,
                    },
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                )
            )
            if imported_any:
                register_outbox_event(
                    OutboxMessage(
                        event_type="operating_fact.imported",
                        aggregate_type="ingestion_batch",
                        aggregate_id=batch.public_id,
                        payload={
                            "batch_public_id": str(batch.public_id),
                            "added_count": added,
                            "revision_count": revisions,
                        },
                        occurred_at=now,
                    )
                )

            return ConfirmBatchResult(
                public_id=batch.public_id,
                added_count=added,
                revision_count=revisions,
                skipped_count=skipped,
                error_count=errors,
                warning_count=warnings,
            )
