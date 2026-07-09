"""Project creation tests for approved candidates."""

from __future__ import annotations

import pytest

from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import ProductDraft
from apps.projects.errors import ProjectCreationFailed
from apps.projects.models import Project
from apps.projects.services.create_project_from_candidate import ApproveAndCreateProject


def raise_database_error(*args, **kwargs) -> None:
    raise ProjectCreationFailed(message="Simulated product draft failure.")


@pytest.mark.django_db(transaction=True)
def test_approve_candidate_creates_one_project_for_repeated_request(
    approved_candidate, boss
) -> None:
    first = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="create-project-1",
    ).execute()
    second = ApproveAndCreateProject(
        context=CommandContext.for_actor(boss),
        candidate_public_id=approved_candidate.public_id,
        idempotency_key="create-project-1",
    ).execute()
    assert first.project.public_id == second.project.public_id
    assert Project.objects.filter(candidate=approved_candidate).count() == 1


@pytest.mark.django_db(transaction=True)
def test_project_creation_failure_rolls_back_product_draft(
    rollback_candidate, boss, monkeypatch
) -> None:
    monkeypatch.setattr(
        "apps.projects.services.create_project_from_candidate.create_product_draft",
        raise_database_error,
    )
    with pytest.raises(ProjectCreationFailed):
        ApproveAndCreateProject(
            context=CommandContext.for_actor(boss),
            candidate_public_id=rollback_candidate.public_id,
            idempotency_key="create-project-fails",
        ).execute()
    assert Project.objects.filter(candidate=rollback_candidate).count() == 0
    assert ProductDraft.objects.filter(project_candidate=rollback_candidate).count() == 0


@pytest.mark.django_db(transaction=True)
def test_approve_candidate_requires_management_and_final_permissions(
    approved_candidate,
    organization: Organization,
    grant_action,
) -> None:
    final_only = User.objects.create_user(
        organization=organization,
        display_name="Final Only",
        status=UserStatus.ACTIVE,
        activated_at=approved_candidate.updated_at,
    )
    grant_action(
        final_only,
        "major_gate.final_decision.record",
        "stage_gate",
        role_code="FINAL_DECISION_ONLY",
    )
    with pytest.raises(PermissionDeniedError):
        ApproveAndCreateProject(
            context=CommandContext.for_actor(final_only),
            candidate_public_id=approved_candidate.public_id,
            idempotency_key="perm-check",
        ).execute()
