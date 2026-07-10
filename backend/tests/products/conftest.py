"""Fixtures for product draft shell tests."""

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
from apps.products.models import (
    AttributeGroupDefinition,
    AttributeGroupValue,
    AttributeOwnerType,
    AttributeValueStatus,
    ChangeSetStatus,
    ChangeSetType,
    ProductAsset,
    ProductChangeSet,
    ProductLifecycleStatus,
    ProductSourceType,
    ProductVersion,
    ProductVersionStatus,
)
from apps.products.services.attribute_schema import compute_attribute_content_hash
from apps.products.services.create_change_set import compute_baseline_fingerprint
from apps.projects.models import Project
from apps.projects.services.create_project_from_candidate import ApproveAndCreateProject
from tests.opportunities.factories import build_approval_ready_candidate
from tests.products.schema_factories import build_published_product_schema


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
def product_asset(
    organization: Organization,
    product_manager: User,
) -> ProductAsset:
    return ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-0001",
        name="High protein yogurt",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.DEVELOPING,
        product_owner=product_manager,
    )


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
        business_no="DRAFT",
    )


@pytest.fixture
def project(approved_candidate: ProjectCandidate, boss: User) -> Project:
    return (
        ApproveAndCreateProject(
            context=CommandContext.for_actor(boss),
            candidate_public_id=approved_candidate.public_id,
            idempotency_key="product-permissions",
        )
        .execute()
        .project
    )


@pytest.fixture
def published_product_schema(organization: Organization, product_asset: ProductAsset) -> object:
    product_asset.category_code = "YOGURT"
    product_asset.save(update_fields=["category_code", "updated_at"])
    return build_published_product_schema(organization=organization, category_code="YOGURT")


@pytest.fixture
def change_set(
    organization: Organization,
    product_asset: ProductAsset,
    product_manager: User,
    published_product_schema: object,
    approved_candidate: ProjectCandidate,
) -> ProductChangeSet:
    del published_product_schema
    product_asset.category_code = "YOGURT"
    product_asset.save(update_fields=["category_code", "updated_at"])
    return ProductChangeSet.objects.create(
        organization=organization,
        change_type=ChangeSetType.NEW_PRODUCT,
        status=ChangeSetStatus.DRAFT,
        product=product_asset,
        project_candidate=approved_candidate,
        title="Yogurt draft",
        created_by=product_manager,
    )


@pytest.fixture
def ready_change_set(
    change_set: ProductChangeSet,
    product_director: User,
    grant_action: Callable[..., None],
    published_product_schema: object,
) -> ProductChangeSet:
    del published_product_schema
    grant_action(product_director, "product.publish_new", "product", role_code="PRODUCT_DIRECTOR")
    change_set.status = ChangeSetStatus.APPROVED
    change_set.approved_by = product_director
    change_set.save(update_fields=["status", "approved_by", "updated_at"])
    return change_set


@pytest.fixture
def iteration_change_set(
    organization: Organization,
    product_manager: User,
    product_director: User,
    opportunity_rules: ConfigurationVersion,
    published_product_schema: object,
) -> ProductChangeSet:
    del published_product_schema
    iteration_candidate = build_approval_ready_candidate(
        organization=organization,
        product_manager=product_manager,
        product_director=product_director,
        business_no="ITER",
    )
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-ITER",
        name="Active yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=product_manager,
    )
    base_version = ProductVersion.objects.create(
        organization=organization,
        product=product,
        version_code="V1",
        version_name="Initial",
        status=ProductVersionStatus.EFFECTIVE,
        definition_summary="Baseline version",
    )
    quality_group = AttributeGroupDefinition.objects.get(
        schema_version__organization=organization,
        schema_version__category_code="YOGURT",
        group_code="QUALITY_COMPLIANCE",
    )
    baseline_values = {"storage_condition": "Room temperature"}
    AttributeGroupValue.objects.create(
        organization=organization,
        owner_type=AttributeOwnerType.VERSION,
        owner_id=base_version.id,
        group_definition=quality_group,
        schema_version=quality_group.schema_version,
        values_json=baseline_values,
        content_hash=compute_attribute_content_hash(baseline_values),
        value_status=AttributeValueStatus.EFFECTIVE,
    )
    base_fingerprint = compute_baseline_fingerprint(product=product, base_version=base_version)
    return ProductChangeSet.objects.create(
        organization=organization,
        change_type=ChangeSetType.ITERATION,
        status=ChangeSetStatus.DRAFT,
        product=product,
        base_version=base_version,
        base_fingerprint=base_fingerprint,
        project_candidate=iteration_candidate,
        title="Quality update",
        created_by=product_manager,
    )
