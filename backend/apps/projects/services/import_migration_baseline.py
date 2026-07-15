"""Import in-flight project migration batches (idempotent by batch_key)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.errors import MigrationImportFailed
from apps.projects.models import (
    MigrationBaseline,
    MigrationBaselineStatus,
    MigrationBatch,
    MigrationBatchStatus,
    MigrationDisposition,
)


@dataclass(frozen=True)
class MigrationImportResult:
    batch: MigrationBatch
    baselines: list[MigrationBaseline]
    accepted_count: int
    error_count: int


@dataclass
class ImportProjectMigrationBatch:
    context: CommandContext
    batch_key: str
    rows: list[dict]

    def execute(self) -> MigrationImportResult:
        actor = self.context.actor
        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="project_migration.confirm",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=None,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            existing = MigrationBatch.objects.filter(
                organization_id=actor.organization_id,
                batch_key=self.batch_key,
            ).first()
            if existing is not None:
                baselines = list(existing.baselines.order_by("id"))
                return MigrationImportResult(
                    batch=existing,
                    baselines=baselines,
                    accepted_count=existing.accepted_row_count,
                    error_count=existing.error_row_count,
                )

            batch = MigrationBatch.objects.create(
                organization=actor.organization,
                batch_key=self.batch_key,
                imported_by=actor,
                status=MigrationBatchStatus.OPEN,
                source_row_count=len(self.rows),
            )
            accepted: list[MigrationBaseline] = []
            errors: list[dict] = []
            for index, row in enumerate(self.rows):
                try:
                    baseline = self._import_row(batch=batch, row=row)
                    accepted.append(baseline)
                except (KeyError, ValueError, IntegrityError) as exc:
                    errors.append(
                        {
                            "row_index": index,
                            "external_project_id": row.get("external_project_id"),
                            "error": str(exc),
                        }
                    )
            if not accepted and self.rows:
                raise MigrationImportFailed(details={"errors": errors})

            batch.accepted_row_count = len(accepted)
            batch.error_row_count = len(errors)
            batch.row_errors = errors
            batch.save(
                update_fields=[
                    "accepted_row_count",
                    "error_row_count",
                    "row_errors",
                    "updated_at",
                ]
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="project_migration.confirm",
                    resource_type="project",
                    resource_public_id=batch.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "batch_key": batch.batch_key,
                        "accepted": batch.accepted_row_count,
                        "errors": batch.error_row_count,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="project_migration.batch_imported",
                    aggregate_type="migration_batch",
                    aggregate_id=batch.public_id,
                    payload={"batch_key": batch.batch_key},
                    occurred_at=self.context.occurred_at,
                )
            )
            return MigrationImportResult(
                batch=batch,
                baselines=accepted,
                accepted_count=len(accepted),
                error_count=len(errors),
            )

    def _import_row(self, *, batch: MigrationBatch, row: dict) -> MigrationBaseline:
        external_id = str(row["external_project_id"]).strip()
        if not external_id:
            raise ValueError("external_project_id is required")
        stage_code = str(row["current_stage_code"]).strip()
        if not stage_code:
            raise ValueError("current_stage_code is required")
        disposition = row.get("disposition") or MigrationDisposition.CONTINUE
        if disposition not in MigrationDisposition.values:
            raise ValueError(f"Invalid disposition: {disposition}")
        return MigrationBaseline.objects.create(
            organization=batch.organization,
            batch=batch,
            external_project_id=external_id,
            name=str(row["name"]).strip(),
            current_stage_code=stage_code,
            leader_display_name=str(row.get("leader_display_name") or ""),
            disposition=disposition,
            history_decision_summary=str(row.get("history_decision_summary") or ""),
            plan_summary=dict(row.get("plan_summary") or {}),
            history_tasks=list(row.get("history_tasks") or []),
            history_files=list(row.get("history_files") or []),
            status=MigrationBaselineStatus.IMPORTED,
        )
