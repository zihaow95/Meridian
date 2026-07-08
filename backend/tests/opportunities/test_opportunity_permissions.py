"""Default-deny authorization for opportunity object identities."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.opportunities.models import (
    InvitationStatus,
    MemberRole,
    Opportunity,
    OpportunityMember,
)


def _resource(
    opportunity: Opportunity,
    *,
    sensitivity: str = DataSensitivityLevel.INTERNAL,
) -> ResourceDescriptor:
    return ResourceDescriptor(
        resource_type="opportunity",
        public_id=opportunity.public_id,
        organization_id=opportunity.organization_id,
        sensitivity_level=sensitivity,
    )


def _authorize(user: User, action: str, resource: ResourceDescriptor) -> bool:
    return authorize(
        subject_for(user),
        action=action,
        resource=resource,
        context=AuthorizationContext.current(),
    ).allowed


@pytest.mark.django_db
def test_unrelated_active_user_is_denied_full_read(
    opportunity: Opportunity, another_active_user: User
) -> None:
    assert not _authorize(another_active_user, "opportunity.full.read", _resource(opportunity))


@pytest.mark.django_db
def test_proposal_owner_is_granted_owner_actions_by_object_identity(
    opportunity: Opportunity, active_user: User
) -> None:
    resource = _resource(opportunity)
    assert _authorize(active_user, "opportunity.full.read", resource)
    assert _authorize(active_user, "opportunity.submit", resource)
    assert _authorize(active_user, "opportunity.export", resource)


@pytest.mark.django_db
def test_accepted_collaborator_reads_full_but_cannot_submit_or_export(
    organization: Organization,
    opportunity: Opportunity,
    another_active_user: User,
) -> None:
    OpportunityMember.objects.create(
        organization=organization,
        opportunity=opportunity,
        user=another_active_user,
        member_role=MemberRole.COLLABORATOR,
        invitation_status=InvitationStatus.ACCEPTED,
        active_from=timezone.now(),
    )
    resource = _resource(opportunity)
    assert _authorize(another_active_user, "opportunity.full.read", resource)
    assert not _authorize(another_active_user, "opportunity.submit", resource)
    assert not _authorize(another_active_user, "opportunity.export", resource)


@pytest.mark.django_db
def test_invited_but_not_accepted_member_is_denied_full_read(
    organization: Organization,
    opportunity: Opportunity,
    another_active_user: User,
) -> None:
    OpportunityMember.objects.create(
        organization=organization,
        opportunity=opportunity,
        user=another_active_user,
        member_role=MemberRole.COLLABORATOR,
        invitation_status=InvitationStatus.INVITED,
        active_from=timezone.now(),
    )
    assert not _authorize(another_active_user, "opportunity.full.read", _resource(opportunity))


@pytest.mark.django_db
def test_platform_admin_cannot_read_high_sensitivity_opportunity_full_text(
    opportunity: Opportunity, platform_admin_user: User
) -> None:
    resource = _resource(opportunity, sensitivity=DataSensitivityLevel.HIGHLY_SENSITIVE)
    assert not _authorize(platform_admin_user, "opportunity.full.read", resource)


@pytest.mark.django_db
def test_collaborator_has_no_sensitive_assessment_authority(
    organization: Organization,
    opportunity: Opportunity,
    another_active_user: User,
) -> None:
    OpportunityMember.objects.create(
        organization=organization,
        opportunity=opportunity,
        user=another_active_user,
        member_role=MemberRole.COLLABORATOR,
        invitation_status=InvitationStatus.ACCEPTED,
        active_from=timezone.now(),
    )
    candidate_resource = ResourceDescriptor(
        resource_type="project_candidate",
        public_id=opportunity.public_id,
        organization_id=opportunity.organization_id,
        sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
    )
    assert not _authorize(another_active_user, "candidate.assessment.edit", candidate_resource)
