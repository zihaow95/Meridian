"""MySQL-enforceable uniqueness for active opportunity members."""

from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.identity.models.user import User
from apps.opportunities.member_keys import active_membership_key
from apps.opportunities.models import (
    InvitationStatus,
    MemberRole,
    Opportunity,
    OpportunityMember,
)
from apps.opportunities.services.create_draft import CreateOpportunityDraft
from apps.platform.application.command import CommandContext


@pytest.mark.django_db
def test_duplicate_active_membership_key_is_rejected(
    opportunity: Opportunity,
    active_user: User,
    another_active_user: User,
) -> None:
    key = active_membership_key(opportunity.id, active_user.id, MemberRole.COLLABORATOR)
    OpportunityMember.objects.create(
        organization=opportunity.organization,
        opportunity=opportunity,
        user=active_user,
        member_role=MemberRole.COLLABORATOR,
        invitation_status=InvitationStatus.ACCEPTED,
        active_from=timezone.now(),
        active_membership_key=key,
    )
    with pytest.raises(IntegrityError):
        OpportunityMember.objects.create(
            organization=opportunity.organization,
            opportunity=opportunity,
            user=another_active_user,
            member_role=MemberRole.COLLABORATOR,
            invitation_status=InvitationStatus.ACCEPTED,
            active_from=timezone.now(),
            active_membership_key=key,
        )


@pytest.mark.django_db
def test_create_draft_sets_active_membership_key(active_user: User, grant_action) -> None:
    grant_action(active_user, "opportunity.create", "opportunity", role_code="PROPOSER")
    opportunity = CreateOpportunityDraft(
        context=CommandContext.for_actor(active_user),
        title="Draft member key",
    ).execute()
    member = OpportunityMember.objects.get(opportunity=opportunity, user=active_user)
    assert member.active_membership_key == active_membership_key(
        opportunity.id,
        active_user.id,
        MemberRole.OWNER,
    )
