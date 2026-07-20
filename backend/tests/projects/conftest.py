"""Fixtures for project shell tests."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from django.utils import timezone

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.identity.models.department import Department, DepartmentStatus
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.opportunities.models import ProjectCandidate
from apps.opportunities.services.configuration import OPPORTUNITY_RULE_DEFINITION_CODE
from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.projects.services.create_project_from_candidate import ApproveAndCreateProject
from tests.opportunities.factories import build_approval_ready_candidate


@pytest.fixture
def opportunity_rules(organization: Organization, active_user: User) -> ConfigurationVersion:
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=OPPORTUNITY_RULE_DEFINITION_CODE,
        name="Proposal rules",
    )
    return ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.PUBLISHED,
        content_json={
            "member_limit": 8,
            "eligible_proposer_roles": ["PROPOSER"],
            "management_conclusion_roles": ["MANAGEMENT_COMMITTEE"],
            "final_decision_roles": ["BOSS"],
            "product_manager_roles": ["PRODUCT_MANAGER"],
            "case_leadership_roles": ["PRODUCT_DIRECTOR"],
            "quota_enforcement_mode": "WARN",
            "quota_minimums": {"USER": 3, "DEPARTMENT": 3},
        },
        created_by=active_user,
        published_by=active_user,
        published_at=timezone.now(),
    )


@pytest.fixture
def default_project_template_content() -> dict:
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2]
        / "apps"
        / "configuration"
        / "defaults"
        / "project_template_v1.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def project_template_version(
    organization: Organization,
    active_user: User,
    default_project_template_content: dict,
) -> ConfigurationVersion:
    now = timezone.now()
    for code in ("PRODUCT", "RD", "OPS"):
        Department.objects.get_or_create(
            organization=organization,
            department_code=code,
            defaults={
                "name": f"{code} Department",
                "status": DepartmentStatus.ACTIVE,
                "valid_from": now,
            },
        )
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code="PROJECT_EXECUTION_TEMPLATE",
        name="Project execution template",
    )
    return ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.PUBLISHED,
        content_json=default_project_template_content,
        content_digest="digest-project-template-v1",
        created_by=active_user,
        published_by=active_user,
        published_at=timezone.now(),
    )


@pytest.fixture
def product_manager(organization: Organization, grant_action: Callable[..., None]) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Product Manager",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(user, "opportunity.full.read", "opportunity", role_code="PRODUCT_MANAGER")
    return user


@pytest.fixture
def product_director(another_active_user: User, grant_action: Callable[..., None]) -> User:
    for action in (
        "candidate.leadership.assign",
        "candidate.assessment.edit",
        "candidate.submit_review",
    ):
        grant_action(another_active_user, action, "project_candidate", role_code="PRODUCT_DIRECTOR")
    return another_active_user


@pytest.fixture
def boss(another_active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(
        another_active_user,
        "major_gate.management_conclusion.record",
        "stage_gate",
        role_code="BOSS",
    )
    grant_action(
        another_active_user,
        "major_gate.final_decision.record",
        "stage_gate",
        role_code="BOSS",
    )
    return another_active_user


@pytest.fixture
def approved_candidate(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
) -> ProjectCandidate:
    return build_approval_ready_candidate(
        organization=organization,
        product_manager=product_manager,
        product_director=product_director,
        business_no="SHELL",
    )


@pytest.fixture
def project(
    approved_candidate: ProjectCandidate,
    boss: User,
    project_template_version: ConfigurationVersion,
) -> Project:
    return (
        ApproveAndCreateProject(
            context=CommandContext.for_actor(boss),
            candidate_public_id=approved_candidate.public_id,
            idempotency_key="project-shell",
        )
        .execute()
        .project
    )
