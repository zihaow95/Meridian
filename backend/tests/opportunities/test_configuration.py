"""Opportunity rule snapshot reads published configuration explicitly."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.services.configuration import (
    OPPORTUNITY_RULE_DEFINITION_CODE,
    OpportunityRuleConfigurationMissing,
    get_opportunity_rule_snapshot,
)


@pytest.mark.django_db
def test_missing_configuration_raises_explicit_error(
    organization: Organization,
) -> None:
    with pytest.raises(OpportunityRuleConfigurationMissing) as exc:
        get_opportunity_rule_snapshot(organization, timezone.now())
    assert exc.value.error_code == "OPPORTUNITY_RULE_NOT_CONFIGURED"


@pytest.mark.django_db
def test_draft_only_configuration_is_not_used(
    organization: Organization, active_user: User
) -> None:
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=OPPORTUNITY_RULE_DEFINITION_CODE,
        name="Proposal rules",
    )
    ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.DRAFT,
        content_json={"member_limit": 8},
        created_by=active_user,
    )
    with pytest.raises(OpportunityRuleConfigurationMissing):
        get_opportunity_rule_snapshot(organization, timezone.now())


@pytest.mark.django_db
def test_published_configuration_is_parsed(organization: Organization, active_user: User) -> None:
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=OPPORTUNITY_RULE_DEFINITION_CODE,
        name="Proposal rules",
    )
    ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.PUBLISHED,
        content_json={
            "member_limit": 8,
            "eligible_proposer_roles": ["PRODUCT_MANAGER", "SALES_DEPT_HEAD"],
            "management_conclusion_roles": ["MANAGEMENT_COMMITTEE"],
            "final_decision_roles": ["BOSS"],
            "quota_enforcement_mode": "WARN",
            "quota_minimums": {"USER": 3, "DEPARTMENT": 3},
        },
        created_by=active_user,
        published_by=active_user,
        published_at=timezone.now(),
    )
    snapshot = get_opportunity_rule_snapshot(organization, timezone.now())
    assert snapshot.member_limit == 8
    assert "PRODUCT_MANAGER" in snapshot.eligible_proposer_roles
    assert snapshot.final_decision_roles == frozenset({"BOSS"})
    assert snapshot.quota_minimums["USER"] == 3
