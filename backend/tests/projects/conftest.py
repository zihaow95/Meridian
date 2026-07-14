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
    stages = [
        {"code": "D1", "name": "项目启动与产品定义", "sequence_no": 1, "depends_on": []},
        {"code": "D2", "name": "配方打样与体验验证", "sequence_no": 2, "depends_on": ["D1"]},
        {"code": "D3", "name": "工艺放大与质量验证", "sequence_no": 3, "depends_on": ["D2"]},
        {"code": "D4", "name": "工程化与试销准备", "sequence_no": 4, "depends_on": ["D3"]},
        {"code": "D5", "name": "上市验证/试销", "sequence_no": 5, "depends_on": ["D4"]},
        {"code": "L1", "name": "正式上市方案", "sequence_no": 6, "depends_on": ["D5"]},
        {
            "code": "L2",
            "name": "首次上市阶段门",
            "sequence_no": 7,
            "depends_on": ["L1"],
            "gate": {"gate_code": "FIRST_LAUNCH", "gate_type": "MAJOR"},
        },
        {"code": "L3", "name": "发布与运营交接", "sequence_no": 8, "depends_on": ["L2"]},
    ]
    return {
        "template_code": "NEW_PRODUCT_DEFAULT_V1",
        "project_type": "NEW_PRODUCT",
        "stages": stages,
        "tasks": [],
        "deliverables": [],
        "gates": [
            {"stage_code": "L2", "gate_code": "FIRST_LAUNCH", "gate_type": "MAJOR"},
        ],
    }


@pytest.fixture
def project_template_version(
    organization: Organization,
    active_user: User,
    default_project_template_content: dict,
) -> ConfigurationVersion:
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
