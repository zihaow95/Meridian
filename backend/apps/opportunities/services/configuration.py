"""Read opportunity workflow rules from published configuration.

Missing configuration is an explicit error; there is no implicit default that
would silently authorize a submission or decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.identity.models.organization import Organization

OPPORTUNITY_RULE_DEFINITION_CODE = "opportunity.proposal_rules"


class OpportunityRuleConfigurationMissing(Exception):
    """Raised when the opportunity rule configuration is not published."""

    error_code = "OPPORTUNITY_RULE_NOT_CONFIGURED"


@dataclass(frozen=True)
class OpportunityRuleSnapshot:
    member_limit: int
    eligible_proposer_roles: frozenset[str]
    management_conclusion_roles: frozenset[str]
    final_decision_roles: frozenset[str]
    product_manager_roles: frozenset[str]
    case_leadership_roles: frozenset[str]
    quota_enforcement_mode: str
    quota_minimums: dict[str, int]
    source_version_id: int


def get_opportunity_rule_snapshot(
    organization: Organization, now: datetime
) -> OpportunityRuleSnapshot:
    definition = ConfigurationDefinition.objects.filter(
        organization=organization,
        definition_code=OPPORTUNITY_RULE_DEFINITION_CODE,
    ).first()
    if definition is None:
        raise OpportunityRuleConfigurationMissing(OpportunityRuleConfigurationMissing.error_code)

    published = (
        ConfigurationVersion.objects.filter(
            definition=definition,
            status=ConfigurationStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
    )
    if published is None:
        raise OpportunityRuleConfigurationMissing(OpportunityRuleConfigurationMissing.error_code)

    content = published.content_json
    return OpportunityRuleSnapshot(
        member_limit=int(content["member_limit"]),
        eligible_proposer_roles=frozenset(content.get("eligible_proposer_roles", [])),
        management_conclusion_roles=frozenset(content.get("management_conclusion_roles", [])),
        final_decision_roles=frozenset(content.get("final_decision_roles", [])),
        product_manager_roles=frozenset(content.get("product_manager_roles", [])),
        case_leadership_roles=frozenset(content.get("case_leadership_roles", [])),
        quota_enforcement_mode=str(content.get("quota_enforcement_mode", "WARN")),
        quota_minimums={
            str(key): int(value) for key, value in content.get("quota_minimums", {}).items()
        },
        source_version_id=published.id,
    )
