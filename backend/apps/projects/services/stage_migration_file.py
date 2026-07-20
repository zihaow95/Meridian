"""Authorize and audit streaming migration file staging."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.storage.base import FileStorage
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.services.migration_file_staging import (
    persist_migration_file_stage,
    write_migration_staging_bytes,
)


def _authorize_migration_stage(actor: User) -> None:
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


@dataclass(frozen=True)
class StageMigrationFile:
    context: CommandContext
    chunks: Iterator[bytes]
    filename: str
    mime_type: str
    storage: FileStorage

    def execute(self) -> dict[str, Any]:
        actor = self.context.actor
        # Fast-fail before streaming large payloads when already denied.
        _authorize_migration_stage(actor)

        staging_name, temp_path, sha256, size_bytes = write_migration_staging_bytes(
            chunks=self.chunks,
            mime_type=self.mime_type,
            storage=self.storage,
            organization=actor.organization,
        )
        try:
            with transaction.atomic():
                # Re-check inside the write transaction (permissions may have changed
                # while bytes were streaming to temp storage).
                _authorize_migration_stage(actor)
                stage = persist_migration_file_stage(
                    organization=actor.organization,
                    uploaded_by=actor,
                    staging_relpath=staging_name,
                    filename=self.filename,
                    mime_type=self.mime_type,
                    sha256=sha256,
                    size_bytes=size_bytes,
                )
                stage_public_id = stage.public_id
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
                            "staging_relpath": staging_name,
                            "sha256": sha256,
                            "size_bytes": size_bytes,
                            "filename": self.filename,
                        },
                    )
                )
                register_outbox_event(
                    OutboxMessage(
                        event_type="project_migration.file_staged",
                        aggregate_type="migration_file_stage",
                        aggregate_id=stage_public_id,
                        payload={
                            "staging_relpath": staging_name,
                            "sha256": sha256,
                            "size_bytes": size_bytes,
                        },
                        occurred_at=self.context.occurred_at,
                    )
                )
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

        return {
            "public_id": str(stage.public_id),
            "filename": self.filename,
            "mime_type": self.mime_type,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "staging_relpath": staging_name,
            "expires_at": stage.expires_at.isoformat(),
        }
