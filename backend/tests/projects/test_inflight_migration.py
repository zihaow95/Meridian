"""In-flight project migration baselines (EXE-014)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.utils import timezone

from apps.identity.models.user import User, UserStatus
from apps.notifications.models import Todo
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.models import (
    MigrationBaseline,
    MigrationDisposition,
    Project,
    ProjectStageStatus,
)
from apps.projects.services.confirm_migration_baseline import ConfirmMigrationBaseline
from apps.projects.services.import_migration_baseline import ImportProjectMigrationBatch
from apps.stage_gates.models import StageGateInstance
from apps.work_items.models import ProfessionalConfirmation, Task


@pytest.fixture
def migrator(organization, grant_action: Callable[..., None]) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Migration Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(user, "project_migration.confirm", "project", role_code="PRODUCT_DIRECTOR")
    return user


def _d3_row(*, external_id: str = "EXT-D3-001") -> dict:
    return {
        "external_project_id": external_id,
        "name": "In-flight yogurt",
        "current_stage_code": "D3",
        "leader_display_name": "Legacy Leader",
        "disposition": MigrationDisposition.CONTINUE,
        "history_decision_summary": "D1/D2 approved offline before Meridian.",
        "plan_summary": {"d3_planned_end": "2026-08-01"},
        "history_tasks": [
            {"task_code": "D1-LEGACY", "name": "Legacy D1", "stage_code": "D1"},
            {"task_code": "D2-LEGACY", "name": "Legacy D2", "stage_code": "D2"},
        ],
        "history_files": [
            {"filename": "d2-report.pdf", "source_note": "NAS archive"},
        ],
    }


@pytest.mark.django_db
def test_import_batch_is_idempotent_by_external_id(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    first = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-1",
        rows=[_d3_row()],
    ).execute()
    second = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-1",
        rows=[_d3_row()],
    ).execute()
    assert first.batch.public_id == second.batch.public_id
    assert MigrationBaseline.objects.filter(batch=first.batch).count() == 1
    assert first.accepted_count == 1
    assert second.accepted_count == 1


@pytest.mark.django_db
def test_unconfirmed_baseline_cannot_continue(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-unconfirmed",
        rows=[_d3_row()],
    ).execute()
    baseline = imported.baselines[0]
    assert baseline.confirmed_at is None
    assert Project.objects.filter(migration_baseline=baseline).count() == 0


@pytest.mark.django_db
def test_continue_from_d3_skips_prior_gates_and_confirmations(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-d3",
        rows=[_d3_row()],
    ).execute()
    baseline = imported.baselines[0]
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.CONTINUE,
        idempotency_key="confirm-d3",
    ).execute()
    project = result.project
    assert project is not None
    stage_codes = list(project.stages.order_by("sequence_no").values_list("stage_code", flat=True))
    assert stage_codes[0] == "D3"
    assert "D1" not in stage_codes
    assert "D2" not in stage_codes
    assert StageGateInstance.objects.filter(project=project, stage_code="D1").count() == 0
    assert StageGateInstance.objects.filter(project=project, stage_code="D2").count() == 0
    assert ProfessionalConfirmation.objects.filter(
        deliverable_revision__deliverable__project=project
    ).count() == 0
    assert Task.objects.filter(project=project, source_type="MIGRATED_HISTORY").count() == 2
    assert project.current_stage.stage_code == "D3"
    assert project.current_stage.status == ProjectStageStatus.ACTIVE


@pytest.mark.django_db
def test_archive_only_creates_no_project_or_todos(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-archive",
        rows=[_d3_row(external_id="EXT-ARC-1")],
    ).execute()
    baseline = imported.baselines[0]
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.ARCHIVE_ONLY,
        idempotency_key="confirm-arc",
    ).execute()
    assert result.project is None
    baseline.refresh_from_db()
    assert baseline.disposition == MigrationDisposition.ARCHIVE_ONLY
    assert Project.objects.filter(migration_baseline=baseline).count() == 0
    assert Todo.objects.filter(
        organization=migrator.organization,
        title__icontains="EXT-ARC-1",
    ).count() == 0


@pytest.mark.django_db
def test_confirm_requires_permission(
    organization,
    grant_action: Callable[..., None],
    project_template_version,
) -> None:
    del project_template_version
    actor = User.objects.create_user(
        organization=organization,
        display_name="No Grant",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    director = User.objects.create_user(
        organization=organization,
        display_name="Import Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(director, "project_migration.confirm", "project", role_code="PRODUCT_DIRECTOR")
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(director),
        batch_key="batch-deny",
        rows=[_d3_row(external_id="EXT-DENY")],
    ).execute()
    with pytest.raises(PermissionDeniedError):
        ConfirmMigrationBaseline(
            context=CommandContext.for_actor(actor),
            baseline_public_id=imported.baselines[0].public_id,
            disposition=MigrationDisposition.CONTINUE,
            idempotency_key="deny-confirm",
        ).execute()
