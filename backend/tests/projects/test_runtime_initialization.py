"""Project runtime initialization from published template snapshot (EXE-001/002)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationSnapshot,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.projects.errors import ProjectTemplateNotPublished
from apps.projects.models import Project, ProjectStage, ProjectStatus
from apps.projects.services.create_project_from_candidate import ApproveAndCreateProject
from apps.projects.services.initialize_runtime import InitializeProjectRuntime

REQUIRED_STAGE_CODES = ("D1", "D2", "D3", "D4", "D5", "L1", "L2", "L3")


@pytest.mark.django_db
def test_approve_creates_d1_l3_and_l2_first_launch(
    approved_candidate,
    boss: User,
    project_template_version: ConfigurationVersion,
) -> None:
    result = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="runtime-init-happy",
    ).execute()

    project = result.project
    stages = list(ProjectStage.objects.filter(project=project).order_by("sequence_no"))
    assert [stage.stage_code for stage in stages] == list(REQUIRED_STAGE_CODES)
    l2 = next(stage for stage in stages if stage.stage_code == "L2")
    assert l2.gate_code == "FIRST_LAUNCH"
    assert project.template_snapshot_id is not None
    assert project.status == ProjectStatus.ACTIVE
    assert project.current_stage is not None
    assert project.current_stage.stage_code == "D1"
    assert project.current_stage.status == "ACTIVE"


@pytest.mark.django_db
def test_runtime_snapshot_isolated_from_later_template_edits(
    approved_candidate,
    boss: User,
    project_template_version: ConfigurationVersion,
) -> None:
    project = (
        ApproveAndCreateProject(
            context=CommandContext.for_actor(boss),
            candidate_public_id=approved_candidate.public_id,
            idempotency_key="runtime-snapshot-isolation",
        )
        .execute()
        .project
    )
    snapshot = ConfigurationSnapshot.objects.get(pk=project.template_snapshot_id)
    original_name = snapshot.content_copy["stages"][0]["name"]

    # Bypass model save guards to prove runtime uses content_copy, not live version.
    mutated = {
        **project_template_version.content_json,
        "stages": [
            {**stage, "name": "MUTATED"}
            for stage in project_template_version.content_json["stages"]
        ],
    }
    ConfigurationVersion.objects.filter(pk=project_template_version.pk).update(content_json=mutated)

    snapshot.refresh_from_db()
    assert snapshot.content_copy["stages"][0]["name"] == original_name
    assert ProjectStage.objects.get(project=project, stage_code="D1").name == original_name


@pytest.mark.django_db
def test_initialize_runtime_is_idempotent(
    approved_candidate,
    boss: User,
    project_template_version: ConfigurationVersion,
) -> None:
    project = (
        ApproveAndCreateProject(
            context=CommandContext.for_actor(boss),
            candidate_public_id=approved_candidate.public_id,
            idempotency_key="runtime-idempotent",
        )
        .execute()
        .project
    )
    first = InitializeProjectRuntime(
        context=CommandContext.for_actor(boss),
        project=project,
        template_version=project_template_version,
    ).execute()
    second = InitializeProjectRuntime(
        context=CommandContext.for_actor(boss),
        project=project,
        template_version=project_template_version,
    ).execute()

    assert first.snapshot.pk == second.snapshot.pk
    assert ProjectStage.objects.filter(project=project).count() == len(REQUIRED_STAGE_CODES)
    assert {stage.pk for stage in first.stages} == {stage.pk for stage in second.stages}


@pytest.mark.django_db
def test_partial_runtime_failure_rolls_back_project_and_stages(
    approved_candidate,
    boss: User,
    organization: Organization,
    active_user: User,
) -> None:
    """Missing published template must not leave a half-created project."""
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code="PROJECT_EXECUTION_TEMPLATE",
        name="Draft only template",
    )
    ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.DRAFT,
        content_json={"stages": []},
        content_digest=f"draft-{uuid4().hex[:8]}",
        created_by=active_user,
    )

    with pytest.raises(ProjectTemplateNotPublished):
        ApproveAndCreateProject(
            context=CommandContext.for_actor(boss),
            candidate_public_id=approved_candidate.public_id,
            idempotency_key="runtime-rollback",
        ).execute()

    assert not Project.objects.filter(candidate=approved_candidate).exists()
    assert not ProjectStage.objects.filter(organization=organization).exists()
