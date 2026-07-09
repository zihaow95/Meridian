"""Accept and decline flows for proposal team invitations."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.opportunities.errors import OpportunityMemberInvitationInvalid
from apps.opportunities.models import InvitationStatus, Opportunity
from apps.opportunities.services.accept_member import AcceptOpportunityMember
from apps.opportunities.services.decline_member import DeclineOpportunityMember
from apps.opportunities.services.invite_member import InviteOpportunityMember
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext


def _resource(opportunity: Opportunity) -> ResourceDescriptor:
    return ResourceDescriptor(
        resource_type="opportunity",
        public_id=opportunity.public_id,
        organization_id=opportunity.organization_id,
    )


def _authorize(user: User, action: str, resource: ResourceDescriptor) -> bool:
    return authorize(
        subject_for(user),
        action=action,
        resource=resource,
        context=AuthorizationContext.current(),
    ).allowed


@pytest.mark.django_db
def test_accept_invitation_grants_collaborator_full_read(
    opportunity: Opportunity,
    active_user: User,
    another_active_user: User,
    grant_action: Callable[..., None],
    opportunity_rules,
) -> None:
    grant_action(active_user, "opportunity.member.invite", "opportunity", role_code="PROPOSER")
    InviteOpportunityMember(
        context=CommandContext.for_actor(active_user),
        opportunity_public_id=opportunity.public_id,
        invitee_public_id=another_active_user.public_id,
    ).execute()
    assert not _authorize(another_active_user, "opportunity.full.read", _resource(opportunity))

    member = AcceptOpportunityMember(
        context=CommandContext.for_actor(another_active_user),
        opportunity_public_id=opportunity.public_id,
    ).execute()
    assert member.invitation_status == InvitationStatus.ACCEPTED
    assert _authorize(another_active_user, "opportunity.full.read", _resource(opportunity))


@pytest.mark.django_db
def test_decline_invitation_denies_full_read_and_releases_membership_key(
    opportunity: Opportunity,
    active_user: User,
    another_active_user: User,
    grant_action: Callable[..., None],
    opportunity_rules,
) -> None:
    grant_action(active_user, "opportunity.member.invite", "opportunity", role_code="PROPOSER")
    invited = InviteOpportunityMember(
        context=CommandContext.for_actor(active_user),
        opportunity_public_id=opportunity.public_id,
        invitee_public_id=another_active_user.public_id,
    ).execute()
    assert invited.active_membership_key is not None

    member = DeclineOpportunityMember(
        context=CommandContext.for_actor(another_active_user),
        opportunity_public_id=opportunity.public_id,
    ).execute()
    assert member.invitation_status == InvitationStatus.DECLINED
    assert member.active_membership_key is None
    assert member.active_to is not None
    assert not _authorize(another_active_user, "opportunity.full.read", _resource(opportunity))


@pytest.mark.django_db
def test_owner_cannot_accept_someone_elses_invitation(
    opportunity: Opportunity,
    active_user: User,
    another_active_user: User,
    grant_action: Callable[..., None],
    opportunity_rules,
) -> None:
    grant_action(active_user, "opportunity.member.invite", "opportunity", role_code="PROPOSER")
    InviteOpportunityMember(
        context=CommandContext.for_actor(active_user),
        opportunity_public_id=opportunity.public_id,
        invitee_public_id=another_active_user.public_id,
    ).execute()

    with pytest.raises(OpportunityMemberInvitationInvalid):
        AcceptOpportunityMember(
            context=CommandContext.for_actor(active_user),
            opportunity_public_id=opportunity.public_id,
        ).execute()


@pytest.mark.django_db
def test_accept_without_pending_invitation_is_rejected(
    organization,
    another_active_user: User,
) -> None:
    from apps.opportunities.models import ProposalStatus

    opportunity = Opportunity.objects.create(
        organization=organization,
        business_no="OPP-INV",
        title="Invite flow",
        proposal_status=ProposalStatus.DRAFT,
        proposal_owner=another_active_user,
        quota_owner_type="USER",
        quota_owner_id=another_active_user.id,
    )
    with pytest.raises(OpportunityMemberInvitationInvalid):
        AcceptOpportunityMember(
            context=CommandContext.for_actor(another_active_user),
            opportunity_public_id=opportunity.public_id,
        ).execute()


@pytest.mark.django_db
def test_declined_member_can_be_reinvited(
    opportunity: Opportunity,
    active_user: User,
    another_active_user: User,
    grant_action: Callable[..., None],
    opportunity_rules,
) -> None:
    grant_action(active_user, "opportunity.member.invite", "opportunity", role_code="PROPOSER")
    InviteOpportunityMember(
        context=CommandContext.for_actor(active_user),
        opportunity_public_id=opportunity.public_id,
        invitee_public_id=another_active_user.public_id,
    ).execute()
    DeclineOpportunityMember(
        context=CommandContext.for_actor(another_active_user),
        opportunity_public_id=opportunity.public_id,
    ).execute()

    replacement = InviteOpportunityMember(
        context=CommandContext.for_actor(active_user),
        opportunity_public_id=opportunity.public_id,
        invitee_public_id=another_active_user.public_id,
    ).execute()
    assert replacement.invitation_status == InvitationStatus.INVITED
    assert replacement.active_membership_key is not None


@pytest.mark.django_db
def test_accept_unknown_opportunity_returns_permission_denied(another_active_user: User) -> None:
    from uuid import uuid4

    with pytest.raises(PermissionDeniedError):
        AcceptOpportunityMember(
            context=CommandContext.for_actor(another_active_user),
            opportunity_public_id=uuid4(),
        ).execute()
