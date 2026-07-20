"""Authorize and audit streaming migration file staging."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.storage.base import FileStorage
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.services.migration_file_staging import stream_stage_migration_file


@dataclass(frozen=True)
class StageMigrationFile:
    context: CommandContext
    chunks: Iterator[bytes]
    filename: str
    mime_type: str
    storage: FileStorage

    def execute(self) -> dict[str, Any]:
        actor = self.context.actor
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

        staged = stream_stage_migration_file(
            chunks=self.chunks,
            filename=self.filename,
            mime_type=self.mime_type,
            storage=self.storage,
            organization=actor.organization,
            uploaded_by=actor,
        )
        stage_public_id = UUID(str(staged["public_id"]))
        append_event(
            AuditRecord(
                actor=actor,
                action_code="project_migration.confirm",
                resource_type="project",
                resource_public_id=stage_public_id,
                result=AuditResult.SUCCESS,
                trace_id=self.context.trace_id,
                occurred_at=self.context.occurred_at,
                acting_roles_snapshot=acting_roles_snapshot(actor),
                after_summary={
                    "staging_relpath": staged["staging_relpath"],
                    "sha256": staged["sha256"],
                    "size_bytes": staged["size_bytes"],
                    "filename": staged["filename"],
                },
            )
        )
        register_outbox_event(
            OutboxMessage(
                event_type="project_migration.file_staged",
                aggregate_type="migration_file_stage",
                aggregate_id=stage_public_id,
                payload={
                    "staging_relpath": staged["staging_relpath"],
                    "sha256": staged["sha256"],
                    "size_bytes": staged["size_bytes"],
                },
                occurred_at=self.context.occurred_at,
            )
        )
        return staged
