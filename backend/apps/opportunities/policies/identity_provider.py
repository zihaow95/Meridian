"""Object identity provider granting minimal actions by opportunity role."""

from __future__ import annotations

from django.db.models import Q

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ObjectIdentity,
    ResourceDescriptor,
)
from apps.authorization.policies.identity_provider import identity_registry

OWNER_ACTIONS: frozenset[str] = frozenset(
    {
        "opportunity.full.read",
        "opportunity.edit",
        "opportunity.withdraw",
        "opportunity.member.invite",
        "opportunity.member.manage",
        "opportunity.export",
    }
)

COLLABORATOR_ACTIONS: frozenset[str] = frozenset(
    {
        "opportunity.full.read",
        "opportunity.edit",
    }
)


class OpportunityIdentityProvider:
    resource_type = "opportunity"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.opportunities.models import (
            InvitationStatus,
            MemberRole,
            Opportunity,
            OpportunityMember,
        )

        if resource.public_id is None:
            return ()

        opportunity = Opportunity.objects.filter(
            public_id=resource.public_id,
            organization_id=resource.organization_id,
        ).first()
        if opportunity is None:
            return ()

        granted: frozenset[str]
        if opportunity.proposal_owner_id == subject.user.id:
            granted = OWNER_ACTIONS
        else:
            member = (
                OpportunityMember.objects.filter(
                    opportunity=opportunity,
                    user=subject.user,
                    invitation_status=InvitationStatus.ACCEPTED,
                    active_from__lte=context.as_of,
                )
                .filter(Q(active_to__isnull=True) | Q(active_to__gt=context.as_of))
                .first()
            )
            if member is None:
                return ()
            granted = (
                OWNER_ACTIONS if member.member_role == MemberRole.OWNER else COLLABORATOR_ACTIONS
            )

        return tuple(ObjectIdentity(action_code=action, resource=resource) for action in granted)


def register_providers() -> None:
    identity_registry.register(OpportunityIdentityProvider())
