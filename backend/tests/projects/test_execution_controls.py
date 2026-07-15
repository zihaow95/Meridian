"""Stage handling, plan changes, and emergency execution (EXE-008/011/013)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.errors import (
    InvalidStageHandlingRequest,
)
from apps.projects.models import (
    EmergencyExecution,
    EmergencyExecutionStatus,
    ExecutionException,
    ExecutionExceptionStatus,
    PlanChangeStatus,
    PlanChangeType,
    Project,
    StageHandlingMode,
)
from apps.projects.services.emergency_execution import CreateEmergencyExecution
from apps.projects.services.exceptions import (
    ConfirmExecutionException,
    RequestStageHandlingMode,
)
from apps.projects.services.plan_changes import ApplyPlanChange, ConfirmPlanChange


@pytest.fixture
def product_director_user(
    organization: Organization,
    grant_action,
) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Phase4 Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    for action, resource in (
        ("stage_handling.confirm", "project_stage"),
        ("plan_change.confirm_important", "project"),
        ("emergency_execution.create", "project"),
        ("project_exception.confirm", "project"),
    ):
        grant_action(user, action, resource, role_code="PRODUCT_DIRECTOR")
    return user


@pytest.mark.django_db
def test_reuse_requires_director_confirmation(
    project: Project, product_director_user: User
) -> None:
    stage = project.stages.get(stage_code="D2")
    pending = RequestStageHandlingMode(
        context=CommandContext.for_actor(project.leader),
        stage_public_id=stage.public_id,
        requested_mode=StageHandlingMode.REUSE,
        rationale="Reuse controlled D2 package",
    ).execute()
    assert pending.status == ExecutionExceptionStatus.PENDING
    stage.refresh_from_db()
    assert stage.handling_mode == StageHandlingMode.EXECUTE

    confirmed = ConfirmExecutionException(
        context=CommandContext.for_actor(product_director_user),
        exception_public_id=pending.public_id,
    ).execute()
    assert confirmed.status == ExecutionExceptionStatus.CONFIRMED
    stage.refresh_from_db()
    assert stage.handling_mode == StageHandlingMode.REUSE
    assert stage.exception_id == confirmed.id


@pytest.mark.django_db
def test_not_applicable_cannot_be_requested(project: Project) -> None:
    stage = project.stages.get(stage_code="D3")
    with pytest.raises(InvalidStageHandlingRequest):
        RequestStageHandlingMode(
            context=CommandContext.for_actor(project.leader),
            stage_public_id=stage.public_id,
            requested_mode=StageHandlingMode.NOT_APPLICABLE,
            rationale="Should come from template only",
        ).execute()


@pytest.mark.django_db
def test_handling_mode_change_preserves_exception_history(
    project: Project, product_director_user: User
) -> None:
    stage = project.stages.get(stage_code="D2")
    first = RequestStageHandlingMode(
        context=CommandContext.for_actor(project.leader),
        stage_public_id=stage.public_id,
        requested_mode=StageHandlingMode.SIMPLIFY,
        rationale="Simplify depth",
    ).execute()
    ConfirmExecutionException(
        context=CommandContext.for_actor(product_director_user),
        exception_public_id=first.public_id,
    ).execute()
    second = RequestStageHandlingMode(
        context=CommandContext.for_actor(project.leader),
        stage_public_id=stage.public_id,
        requested_mode=StageHandlingMode.PARALLEL,
        rationale="Parallelize with D3",
    ).execute()
    ConfirmExecutionException(
        context=CommandContext.for_actor(product_director_user),
        exception_public_id=second.public_id,
    ).execute()
    assert ExecutionException.objects.filter(stage=stage).count() == 2
    assert (
        ExecutionException.objects.filter(
            stage=stage, status=ExecutionExceptionStatus.CONFIRMED
        ).count()
        == 2
    )


@pytest.mark.django_db
def test_minor_plan_change_applies_for_leader(project: Project) -> None:
    stage = project.stages.get(stage_code="D1")
    before = stage.planned_end_at
    change = ApplyPlanChange(
        context=CommandContext.for_actor(project.leader),
        project_public_id=project.public_id,
        change_type=PlanChangeType.MINOR,
        target_type="project_stage",
        target_public_id=stage.public_id,
        field_name="planned_end_at",
        before_value=str(before) if before else "",
        after_value="2026-08-01T00:00:00+00:00",
        impact_summary="Slip one week",
    ).execute()
    assert change.status == PlanChangeStatus.APPLIED
    stage.refresh_from_db()
    assert stage.planned_end_at is not None
    assert stage.planned_end_at.isoformat().startswith("2026-08-01")


@pytest.mark.django_db
def test_important_plan_change_needs_director(
    project: Project,
    product_director_user: User,
) -> None:
    stage = project.stages.get(stage_code="D1")
    pending = ApplyPlanChange(
        context=CommandContext.for_actor(project.leader),
        project_public_id=project.public_id,
        change_type=PlanChangeType.IMPORTANT,
        target_type="project_stage",
        target_public_id=stage.public_id,
        field_name="planned_end_at",
        before_value="",
        after_value="2026-09-01T00:00:00+00:00",
        impact_summary="Major slip",
    ).execute()
    assert pending.status == PlanChangeStatus.PENDING_CONFIRMATION
    stage.refresh_from_db()
    assert stage.planned_end_at is None

    confirmed = ConfirmPlanChange(
        context=CommandContext.for_actor(product_director_user),
        change_public_id=pending.public_id,
    ).execute()
    assert confirmed.status == PlanChangeStatus.CONFIRMED
    stage.refresh_from_db()
    assert stage.planned_end_at is not None


@pytest.mark.django_db
def test_leader_cannot_create_emergency_execution(project: Project) -> None:
    with pytest.raises(PermissionDeniedError):
        CreateEmergencyExecution(
            context=CommandContext.for_actor(project.leader),
            project_public_id=project.public_id,
            subject_summary="Start pilot early",
            pending_confirmation="Gate package",
            due_at=timezone.now() + timedelta(days=3),
        ).execute()


@pytest.mark.django_db
def test_director_can_create_emergency_execution(
    project: Project,
    product_director_user: User,
) -> None:
    record = CreateEmergencyExecution(
        context=CommandContext.for_actor(product_director_user),
        project_public_id=project.public_id,
        subject_summary="Start pilot early",
        pending_confirmation="Gate package",
        due_at=timezone.now() + timedelta(days=3),
    ).execute()
    assert record.status == EmergencyExecutionStatus.OPEN
    assert EmergencyExecution.objects.filter(project=project).count() == 1
