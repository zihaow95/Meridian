"""Confirm a migration baseline as CONTINUE or ARCHIVE_ONLY."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.configuration.models import ConfigurationStatus, ConfigurationVersion
from apps.configuration.services import CreateSnapshot
from apps.documents.services.ingest import activate_staged_content
from apps.documents.storage.base import FileStorage
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.errors import (
    MigrationBaselineAlreadyConfirmed,
    MigrationImportFailed,
    ProjectTemplateInvalid,
    ProjectTemplateNotPublished,
)
from apps.projects.models import (
    MigrationBaseline,
    MigrationBaselineStatus,
    MigrationDisposition,
    Project,
    ProjectRole,
    ProjectStage,
    ProjectStageStatus,
    ProjectStatus,
    ProjectType,
    StageHandlingMode,
)
from apps.projects.services.appoint_member import AppointProjectMember
from apps.projects.services.initialize_runtime import (
    PROJECT_EXECUTION_TEMPLATE_CODE,
    require_template_departments,
)
from apps.projects.services.migration_activation import activate_or_recover_history_file
from apps.projects.services.migration_file_staging import mark_staged_files_consumed
from apps.stage_gates.services.open_execution_gates import open_execution_gates_for_stages
from apps.work_items.services.materialize_template import (
    materialize_template_deliverables,
    materialize_template_tasks,
)
from apps.work_items.services.migrated_history import (
    MigratedFileStage,
    attach_migrated_history_deliverable,
    create_migrated_history_task,
    stage_migrated_history_file,
)


@dataclass(frozen=True)
class ConfirmMigrationResult:
    baseline: MigrationBaseline
    project: Project | None


def _resolve_migration_leader(*, baseline: MigrationBaseline, actor: User) -> User:
    plan = baseline.plan_summary or {}
    leader_pid = plan.get("leader_public_id")
    if leader_pid:
        matched = User.objects.filter(
            public_id=leader_pid,
            organization_id=baseline.organization_id,
        ).first()
        if matched is not None:
            return matched
    if baseline.leader_display_name:
        matched = User.objects.filter(
            organization_id=baseline.organization_id,
            display_name=baseline.leader_display_name,
        ).first()
        if matched is not None:
            return matched
    return actor


def _history_file_audit_metadata(items: list[Any]) -> list[dict[str, Any]]:
    """Audit-safe metadata for migrated files (never binary content)."""

    metadata: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            metadata.append({"filename": str(item)})
            continue
        metadata.append(
            {
                "filename": str(item.get("filename") or item.get("name") or "migrated-file"),
                "deliverable_code": item.get("deliverable_code"),
                "source_version": item.get("source_version")
                or item.get("migration_source_version"),
                "mime_type": item.get("mime_type"),
                "sha256": item.get("sha256"),
                "size_bytes": item.get("size_bytes"),
            }
        )
    return metadata


def _drop_staging_relpaths(items: list[Any]) -> list[dict[str, Any]]:
    """Keep durable metadata after activation; drop ephemeral staging paths."""

    cleaned: list[dict[str, Any]] = []
    consumed: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            cleaned.append({"filename": str(item)})
            continue
        rel = item.get("staging_relpath")
        if rel:
            consumed.append(str(rel).replace("\\", "/"))
        cleaned.append(
            {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "content_base64",
                    "content_text",
                    "content",
                    "staging_relpath",
                    "stage_public_id",
                }
            }
        )
    mark_staged_files_consumed(consumed)
    return cleaned


def _remember_pending_version(
    items: list[Any],
    *,
    deliverable_code: str,
    staging_relpath: str | None,
    version_public_id: str,
) -> list[dict[str, Any]]:
    """Bind a PENDING version id to exactly one history file row."""

    updated: list[dict[str, Any]] = []
    matched = False
    for item in items:
        if not isinstance(item, dict):
            updated.append({"filename": str(item)})
            continue
        row = dict(item)
        if matched:
            updated.append(row)
            continue
        code = str(row.get("deliverable_code") or "")
        rel = str(row.get("staging_relpath") or "")
        if staging_relpath and rel == staging_relpath:
            row["pending_version_public_id"] = version_public_id
            matched = True
        elif deliverable_code and code == deliverable_code:
            row["pending_version_public_id"] = version_public_id
            matched = True
        updated.append(row)
    return updated


def _filter_content_for_stages(content: dict[str, Any], stage_codes: set[str]) -> dict[str, Any]:
    filtered = dict(content)
    filtered["tasks"] = [
        entry
        for entry in (content.get("tasks") or [])
        if str(entry.get("stage_code")) in stage_codes
    ]
    remaining_task_codes = {str(entry.get("task_code")) for entry in filtered["tasks"]}
    filtered["tasks"] = [
        {
            **entry,
            "depends_on": [
                pred
                for pred in (entry.get("depends_on") or [])
                if str(pred) in remaining_task_codes
            ],
        }
        for entry in filtered["tasks"]
    ]
    filtered["deliverables"] = [
        entry
        for entry in (content.get("deliverables") or [])
        if str(entry.get("stage_code")) in stage_codes
    ]
    filtered["gates"] = [
        entry
        for entry in (content.get("gates") or [])
        if str(entry.get("stage_code")) in stage_codes
    ]
    return filtered


@dataclass
class ConfirmMigrationBaseline:
    context: CommandContext
    baseline_public_id: UUID
    disposition: str
    idempotency_key: str

    def execute(self) -> ConfirmMigrationResult:
        actor = self.context.actor
        self._pending_migrated_files: list[MigratedFileStage] = []
        self._attach_stage: ProjectStage | None = None
        storage = get_file_storage()
        with transaction.atomic():
            baseline = (
                MigrationBaseline.objects.select_for_update()
                .select_related("batch")
                .filter(
                    public_id=self.baseline_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if baseline is None:
                raise PermissionDeniedError()

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

            if baseline.status == MigrationBaselineStatus.CONFIRMED:
                if baseline.confirm_idempotency_key == self.idempotency_key:
                    project = Project.objects.filter(migration_baseline=baseline).first()
                    if project is not None:
                        self._finish_migrated_history_files(
                            project=project,
                            baseline=baseline,
                            actor=actor,
                            storage=storage,
                        )
                    return ConfirmMigrationResult(baseline=baseline, project=project)
                raise MigrationBaselineAlreadyConfirmed()

            conflicting = (
                MigrationBaseline.objects.filter(
                    organization_id=actor.organization_id,
                    confirm_idempotency_key=self.idempotency_key,
                )
                .exclude(pk=baseline.pk)
                .first()
            )
            if conflicting is not None:
                raise MigrationImportFailed(
                    message="Idempotency key is already bound to another migration baseline."
                )

            if self.disposition not in MigrationDisposition.values:
                raise MigrationImportFailed(message=f"Invalid disposition: {self.disposition}")

            baseline.disposition = self.disposition
            baseline.status = MigrationBaselineStatus.CONFIRMED
            baseline.confirmed_by = actor
            baseline.confirmed_at = self.context.occurred_at
            baseline.confirm_idempotency_key = self.idempotency_key
            baseline.save(
                update_fields=[
                    "disposition",
                    "status",
                    "confirmed_by",
                    "confirmed_at",
                    "confirm_idempotency_key",
                    "updated_at",
                ]
            )

            history_file_metadata = _history_file_audit_metadata(
                list(baseline.history_deliverables or []) + list(baseline.history_files or [])
            )

            project = None
            if self.disposition == MigrationDisposition.CONTINUE:
                project = self._materialize_continued_project(baseline=baseline, actor=actor)

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="project_migration.confirm",
                    resource_type="project",
                    resource_public_id=project.public_id if project else baseline.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "baseline_public_id": str(baseline.public_id),
                        "disposition": baseline.disposition,
                        "project_public_id": str(project.public_id) if project else None,
                        "history_files": history_file_metadata,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="project_migration.baseline_confirmed",
                    aggregate_type="migration_baseline",
                    aggregate_id=baseline.public_id,
                    payload={
                        "disposition": baseline.disposition,
                        "project_public_id": str(project.public_id) if project else None,
                    },
                    occurred_at=self.context.occurred_at,
                )
            )
            result = ConfirmMigrationResult(baseline=baseline, project=project)

        # Activate after commit, then attach business references only to ACTIVE files.
        if result.project is not None:
            self._activate_and_attach_pending(
                project=result.project,
                actor=actor,
                storage=storage,
                baseline=result.baseline,
            )
            baseline = MigrationBaseline.objects.get(pk=result.baseline.pk)
            if not self._pending_migrated_files:
                baseline.history_files = _drop_staging_relpaths(list(baseline.history_files or []))
                baseline.history_deliverables = _drop_staging_relpaths(
                    list(baseline.history_deliverables or [])
                )
                baseline.save(update_fields=["history_files", "history_deliverables", "updated_at"])
            result = ConfirmMigrationResult(baseline=baseline, project=result.project)
        elif result.baseline.disposition == MigrationDisposition.ARCHIVE_ONLY:
            baseline = self._activate_archived_history_files(
                baseline=result.baseline,
                actor=actor,
                storage=storage,
            )
            result = ConfirmMigrationResult(baseline=baseline, project=None)

        return result

    def _activate_archived_history_files(
        self,
        *,
        baseline: MigrationBaseline,
        actor: User,
        storage: FileStorage,
    ) -> MigrationBaseline:
        """Activate ARCHIVE_ONLY history files into formal DocumentVersions and consume stages."""

        from uuid import uuid4

        from apps.documents.models import DocumentSource
        from apps.documents.services.ingest import stage_controlled_content
        from apps.projects.services.migration_file_staging import resolve_migration_staging_path

        def _normalize_item(item: Any) -> dict[str, Any]:
            if isinstance(item, dict):
                return dict(item)
            return {"filename": str(item)}

        def _clean_row(row: dict[str, Any]) -> dict[str, Any]:
            return {
                key: value
                for key, value in row.items()
                if key
                not in {
                    "content_base64",
                    "content_text",
                    "content",
                    "staging_relpath",
                    "stage_public_id",
                }
            }

        def _activate_items(field_name: str) -> list[dict[str, Any]]:
            items = [_normalize_item(item) for item in (getattr(baseline, field_name) or [])]
            staged_moves: list[tuple[int, Any, str | None]] = []
            for index, row in enumerate(items):
                if row.get("document_version_public_id") and not row.get(
                    "pending_version_public_id"
                ):
                    row["pending_version_public_id"] = row["document_version_public_id"]
                if row.get("pending_version_public_id"):
                    version = activate_or_recover_history_file(
                        row,
                        organization_id=baseline.organization_id,
                        storage=storage,
                    )
                    if version is not None:
                        row["document_version_public_id"] = str(version.public_id)
                        row["pending_version_public_id"] = str(version.public_id)
                    items[index] = row
                    continue
                staging_relpath = row.get("staging_relpath")
                if not staging_relpath:
                    items[index] = row
                    continue
                temp_path = resolve_migration_staging_path(storage, str(staging_relpath))
                if not temp_path.is_file():
                    raise MigrationImportFailed(
                        message=f"Staged migration file missing on disk: {staging_relpath}"
                    )
                sha256 = str(row.get("sha256") or "")
                size_bytes = int(row.get("size_bytes") or 0)
                if not sha256 or size_bytes <= 0:
                    raise MigrationImportFailed(
                        message="Archived history file requires sha256/size_bytes."
                    )
                filename = str(row.get("filename") or row.get("name") or "migrated-file")
                mime = str(row.get("mime_type") or "application/octet-stream")
                pending_version, staged = stage_controlled_content(
                    organization=baseline.organization,
                    source_temp_path=temp_path,
                    sha256=sha256,
                    size_bytes=size_bytes,
                    original_filename=filename,
                    mime_type=mime,
                    uploaded_by=actor,
                    source=DocumentSource.MIGRATION,
                    category="MIGRATION_ARCHIVE",
                    document_code=f"MIG-ARC-{uuid4().hex[:12].upper()}",
                    title=filename,
                )
                row["pending_version_public_id"] = str(pending_version.public_id)
                items[index] = row
                staged_moves.append((index, staged, str(staging_relpath).replace("\\", "/")))

            setattr(baseline, field_name, items)
            baseline.save(update_fields=[field_name, "updated_at"])

            consumed: list[str] = []
            for index, staged, rel in staged_moves:
                version = activate_staged_content(staged, storage)
                items[index]["document_version_public_id"] = str(version.public_id)
                items[index]["pending_version_public_id"] = str(version.public_id)
                if rel:
                    consumed.append(rel)
            mark_staged_files_consumed(consumed)
            return [_clean_row(row) for row in items]

        baseline.history_files = _activate_items("history_files")
        baseline.history_deliverables = _activate_items("history_deliverables")
        baseline.save(update_fields=["history_files", "history_deliverables", "updated_at"])
        return MigrationBaseline.objects.get(pk=baseline.pk)

    def _activate_and_attach_pending(
        self,
        *,
        project: Project,
        actor: User,
        storage: FileStorage,
        baseline: MigrationBaseline | None = None,
    ) -> None:
        attach_stage = self._attach_stage or project.current_stage
        if attach_stage is None:
            raise MigrationImportFailed(message="Migrated history files require an active stage.")
        remaining: list[MigratedFileStage] = []
        first_error: Exception | None = None
        for pending in self._pending_migrated_files:
            try:
                # Persist the version id before the move so retries no longer need
                # the ephemeral staging temp file.
                if baseline is not None:
                    baseline.history_files = _remember_pending_version(
                        list(baseline.history_files or []),
                        deliverable_code=pending.deliverable_code,
                        staging_relpath=pending.staging_relpath,
                        version_public_id=pending.version_public_id,
                    )
                    baseline.history_deliverables = _remember_pending_version(
                        list(baseline.history_deliverables or []),
                        deliverable_code=pending.deliverable_code,
                        staging_relpath=pending.staging_relpath,
                        version_public_id=pending.version_public_id,
                    )
                    baseline.save(
                        update_fields=["history_files", "history_deliverables", "updated_at"]
                    )
                version = activate_staged_content(pending.staged, storage)
                attach_migrated_history_deliverable(
                    project=project,
                    stage=attach_stage,
                    version=version,
                    filename=pending.filename,
                    deliverable_code=pending.deliverable_code,
                    source_note=pending.source_note,
                    source_version=pending.source_version,
                    sha256=pending.sha256,
                    actor=actor,
                )
            except Exception as exc:  # noqa: BLE001 - preserve for idempotent retry
                remaining.append(pending)
                if first_error is None:
                    first_error = exc
        self._pending_migrated_files = remaining
        if first_error is not None:
            raise first_error

    def _finish_migrated_history_files(
        self,
        *,
        project: Project,
        baseline: MigrationBaseline,
        actor: User,
        storage: FileStorage,
    ) -> None:
        """Idempotent retry: complete PENDING activations and attach missing deliverables."""

        attach_stage = project.current_stage
        if attach_stage is None:
            return
        self._pending_migrated_files = []
        self._attach_stage = attach_stage
        for item in list(baseline.history_deliverables or []) + list(baseline.history_files or []):
            if not isinstance(item, dict):
                continue
            code = str(item.get("deliverable_code") or "")
            if code:
                existing = project.deliverables.filter(deliverable_code=code).first()
                if existing is not None and existing.current_revision_id is not None:
                    continue
            recovered = None
            if item.get("pending_version_public_id"):
                recovered = activate_or_recover_history_file(
                    item,
                    organization_id=project.organization_id,
                    storage=storage,
                )
            if recovered is not None:
                attach_migrated_history_deliverable(
                    project=project,
                    stage=attach_stage,
                    version=recovered,
                    filename=str(item.get("filename") or item.get("name") or "migrated-file"),
                    deliverable_code=code or f"MIG-FILE-{recovered.public_id.hex[:10]}",
                    source_note=str(item.get("source_note") or "Migrated history file"),
                    source_version=str(
                        item.get("source_version") or item.get("migration_source_version") or "1"
                    ),
                    sha256=str(item.get("sha256") or recovered.file_object.sha256),
                    actor=actor,
                )
                continue
            pending = stage_migrated_history_file(
                project=project,
                item=item,
                actor=actor,
                storage=storage,
            )
            if pending is not None:
                self._pending_migrated_files.append(pending)
        if self._pending_migrated_files:
            self._activate_and_attach_pending(
                project=project, actor=actor, storage=storage, baseline=baseline
            )
        baseline.refresh_from_db()
        if not self._pending_migrated_files:
            baseline.history_files = _drop_staging_relpaths(list(baseline.history_files or []))
            baseline.history_deliverables = _drop_staging_relpaths(
                list(baseline.history_deliverables or [])
            )
            baseline.save(update_fields=["history_files", "history_deliverables", "updated_at"])

    def _materialize_continued_project(
        self,
        *,
        baseline: MigrationBaseline,
        actor: User,
    ) -> Project:
        template = (
            ConfigurationVersion.objects.filter(
                organization_id=baseline.organization_id,
                definition__definition_code=PROJECT_EXECUTION_TEMPLATE_CODE,
                status=ConfigurationStatus.PUBLISHED,
            )
            .select_related("definition")
            .order_by("-version_number")
            .first()
        )
        if template is None:
            raise ProjectTemplateNotPublished()

        snapshot = CreateSnapshot(
            version=template,
            reference_type="project_migration",
            reference_id=baseline.public_id,
            actor=actor,
            context=self.context,
        ).execute()

        content = snapshot.content_copy
        stages_def = list(content.get("stages") or [])
        by_code = {entry["code"]: entry for entry in stages_def}
        if baseline.current_stage_code not in by_code:
            raise MigrationImportFailed(
                message=f"Unknown current stage: {baseline.current_stage_code}"
            )
        current_seq = int(by_code[baseline.current_stage_code]["sequence_no"])
        remaining = [entry for entry in stages_def if int(entry["sequence_no"]) >= current_seq]
        remaining_codes = {entry["code"] for entry in remaining}
        filtered_content = _filter_content_for_stages(content, remaining_codes)

        project = Project.objects.create(
            organization=baseline.organization,
            business_no=f"MIG-{baseline.external_project_id}"[:32],
            name=baseline.name,
            project_type=ProjectType.NEW_PRODUCT,
            status=ProjectStatus.ACTIVE,
            candidate=None,
            leader=actor,
            template_snapshot=snapshot,
            migration_baseline=baseline,
            idempotency_key=f"migration:{baseline.public_id}",
            actual_start_at=self.context.occurred_at,
        )

        created_stages: list[ProjectStage] = []
        for entry in remaining:
            gate = entry.get("gate") or {}
            stage = ProjectStage.objects.create(
                organization=baseline.organization,
                project=project,
                stage_code=entry["code"],
                name=entry["name"],
                sequence_no=int(entry["sequence_no"]),
                status=(
                    ProjectStageStatus.ACTIVE
                    if entry["code"] == baseline.current_stage_code
                    else ProjectStageStatus.NOT_STARTED
                ),
                handling_mode=StageHandlingMode.EXECUTE,
                gate_code=str(gate.get("gate_code") or ""),
                gate_type=str(gate.get("gate_type") or ""),
                depends_on=[
                    code for code in (entry.get("depends_on") or []) if code in remaining_codes
                ],
                actual_start_at=(
                    self.context.occurred_at
                    if entry["code"] == baseline.current_stage_code
                    else None
                ),
            )
            created_stages.append(stage)

        current = next(
            stage for stage in created_stages if stage.stage_code == baseline.current_stage_code
        )
        project.current_stage = current
        planned_end = (baseline.plan_summary or {}).get("planned_end_at")
        if planned_end:
            from django.utils.dateparse import parse_datetime

            parsed = parse_datetime(str(planned_end))
            if parsed is not None:
                current.planned_end_at = parsed
                current.save(update_fields=["planned_end_at", "updated_at"])
                project.planned_end_at = parsed
        project.save(update_fields=["current_stage", "planned_end_at", "updated_at"])

        try:
            require_template_departments(baseline.organization_id)
        except ProjectTemplateInvalid as exc:
            raise MigrationImportFailed(message=str(exc)) from exc

        department = Department.objects.filter(
            organization=baseline.organization,
            department_code="PRODUCT",
            status=DepartmentStatus.ACTIVE,
        ).first()
        if department is None:
            raise MigrationImportFailed(message="PRODUCT department is required for migration.")

        leader = _resolve_migration_leader(baseline=baseline, actor=actor)
        project.leader = leader
        project.save(update_fields=["leader", "updated_at"])

        for item in baseline.history_tasks:
            try:
                create_migrated_history_task(
                    project=project,
                    stage=current,
                    item=item if isinstance(item, dict) else {"name": str(item)},
                    department=department,
                )
            except IntegrityError as exc:
                raise MigrationImportFailed(
                    message=f"Failed to materialize history task: {item.get('task_code')}"
                ) from exc

        storage = get_file_storage()
        self._attach_stage = current
        for item in list(baseline.history_deliverables or []) + list(baseline.history_files or []):
            pending = stage_migrated_history_file(
                project=project,
                item=item if isinstance(item, dict) else {"filename": str(item)},
                actor=actor,
                storage=storage,
            )
            if pending is not None:
                self._pending_migrated_files.append(pending)

        stages_by_code = {stage.stage_code: stage for stage in created_stages}
        materialize_template_tasks(
            project=project,
            stages_by_code=stages_by_code,
            content=filtered_content,
            default_department=department,
        )
        materialize_template_deliverables(
            project=project,
            stages_by_code=stages_by_code,
            content=filtered_content,
        )
        open_execution_gates_for_stages(
            project=project,
            stages=created_stages,
            content=filtered_content,
            ready_stage_codes={baseline.current_stage_code},
        )

        AppointProjectMember(
            context=self.context,
            project_public_id=project.public_id,
            user_public_id=leader.public_id,
            project_role=ProjectRole.LEADER,
        ).execute()

        for member in (baseline.plan_summary or {}).get("members") or []:
            member_id = member.get("user_public_id") if isinstance(member, dict) else None
            role = (
                str(member.get("project_role") or ProjectRole.MEMBER)
                if isinstance(member, dict)
                else ProjectRole.MEMBER
            )
            if not member_id:
                continue
            AppointProjectMember(
                context=self.context,
                project_public_id=project.public_id,
                user_public_id=UUID(str(member_id)),
                project_role=role if role in ProjectRole.values else ProjectRole.MEMBER,
            ).execute()

        return project
