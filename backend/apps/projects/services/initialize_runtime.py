"""Initialize project stages from a published execution template snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.configuration.models import ConfigurationSnapshot, ConfigurationStatus, ConfigurationVersion
from apps.configuration.services import CreateSnapshot
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.projects.errors import ProjectTemplateInvalid, ProjectTemplateNotPublished
from apps.projects.models import (
    Project,
    ProjectStage,
    ProjectStageStatus,
    ProjectStatus,
    ProjectTemplateSnapshot,
    StageHandlingMode,
)

PROJECT_EXECUTION_TEMPLATE_CODE = "PROJECT_EXECUTION_TEMPLATE"
REQUIRED_STAGE_CODES = ("D1", "D2", "D3", "D4", "D5", "L1", "L2", "L3")


@dataclass(frozen=True)
class ProjectRuntimeResult:
    snapshot: ConfigurationSnapshot
    stages: list[ProjectStage]
    gates: list[ProjectStage]


@dataclass
class InitializeProjectRuntime:
    context: CommandContext
    project: Project
    template_version: ConfigurationVersion | None = None

    def execute(self) -> ProjectRuntimeResult:
        existing = self._existing_runtime()
        if existing is not None:
            return existing

        version = self._resolve_published_version()
        validate_project_template_content(version.content_json)

        snapshot = CreateSnapshot(
            version=version,
            reference_type="project",
            reference_id=self.project.public_id,
            actor=self.context.actor,
            context=self.context,
        ).execute()

        ProjectTemplateSnapshot.objects.create(
            organization=self.project.organization,
            project=self.project,
            configuration_snapshot=snapshot,
            source_version=version,
        )

        stages = self._expand_stages(snapshot.content_copy)
        gates = [stage for stage in stages if stage.gate_code]
        d1 = next(stage for stage in stages if stage.stage_code == "D1")
        d1.status = ProjectStageStatus.ACTIVE
        d1.actual_start_at = self.context.occurred_at
        d1.save(update_fields=["status", "actual_start_at", "updated_at"])

        self.project.template_snapshot = snapshot
        self.project.current_stage = d1
        self.project.status = ProjectStatus.ACTIVE
        self.project.actual_start_at = self.context.occurred_at
        self.project.save(
            update_fields=[
                "template_snapshot",
                "current_stage",
                "status",
                "actual_start_at",
                "updated_at",
            ]
        )

        append_event(
            AuditRecord(
                actor=self.context.actor,
                action_code="project.initialized",
                resource_type="project",
                resource_public_id=self.project.public_id,
                result=AuditResult.SUCCESS,
                trace_id=self.context.trace_id,
                occurred_at=self.context.occurred_at,
                acting_roles_snapshot=acting_roles_snapshot(self.context.actor),
                after_summary={
                    "template_version_id": str(version.public_id),
                    "snapshot_id": str(snapshot.public_id),
                    "stage_count": len(stages),
                },
            )
        )
        register_outbox_event(
            OutboxMessage(
                event_type="project.initialized",
                aggregate_type="project",
                aggregate_id=self.project.public_id,
                payload={
                    "project_public_id": str(self.project.public_id),
                    "snapshot_public_id": str(snapshot.public_id),
                },
                occurred_at=self.context.occurred_at,
            )
        )

        return ProjectRuntimeResult(snapshot=snapshot, stages=stages, gates=gates)

    def _existing_runtime(self) -> ProjectRuntimeResult | None:
        if self.project.template_snapshot_id is None:
            return None
        stages = list(ProjectStage.objects.filter(project=self.project).order_by("sequence_no"))
        if not stages:
            return None
        return ProjectRuntimeResult(
            snapshot=self.project.template_snapshot,
            stages=stages,
            gates=[stage for stage in stages if stage.gate_code],
        )

    def _resolve_published_version(self) -> ConfigurationVersion:
        if self.template_version is not None:
            if self.template_version.status != ConfigurationStatus.PUBLISHED:
                raise ProjectTemplateNotPublished()
            if self.template_version.definition.definition_code != PROJECT_EXECUTION_TEMPLATE_CODE:
                raise ProjectTemplateInvalid(message="Unexpected template definition code.")
            return self.template_version

        version = (
            ConfigurationVersion.objects.filter(
                organization_id=self.project.organization_id,
                definition__definition_code=PROJECT_EXECUTION_TEMPLATE_CODE,
                status=ConfigurationStatus.PUBLISHED,
            )
            .select_related("definition")
            .order_by("-version_number")
            .first()
        )
        if version is None:
            raise ProjectTemplateNotPublished()
        return version

    def _expand_stages(self, content: dict[str, Any]) -> list[ProjectStage]:
        created: list[ProjectStage] = []
        for entry in content.get("stages", []):
            gate = entry.get("gate") or {}
            stage = ProjectStage.objects.create(
                organization=self.project.organization,
                project=self.project,
                stage_code=entry["code"],
                name=entry["name"],
                sequence_no=int(entry["sequence_no"]),
                status=ProjectStageStatus.NOT_STARTED,
                handling_mode=StageHandlingMode.EXECUTE,
                gate_code=str(gate.get("gate_code") or ""),
                gate_type=str(gate.get("gate_type") or ""),
                depends_on=list(entry.get("depends_on") or []),
            )
            created.append(stage)
        return created


def validate_project_template_content(content: dict[str, Any]) -> None:
    stages = content.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ProjectTemplateInvalid(message="Template stages are required.")

    codes = [stage.get("code") for stage in stages]
    if len(codes) != len(set(codes)):
        raise ProjectTemplateInvalid(message="Stage codes must be unique.")
    if any(code not in codes for code in REQUIRED_STAGE_CODES):
        raise ProjectTemplateInvalid(message="Template must include D1—L3 stage codes.")

    code_set = set(codes)
    for stage in stages:
        for dep in stage.get("depends_on") or []:
            if dep not in code_set:
                raise ProjectTemplateInvalid(message=f"Unknown stage dependency: {dep}")

    l2 = next((stage for stage in stages if stage.get("code") == "L2"), None)
    gate = (l2 or {}).get("gate") or {}
    if gate.get("gate_code") != "FIRST_LAUNCH":
        raise ProjectTemplateInvalid(message="L2 must use FIRST_LAUNCH major gate.")
