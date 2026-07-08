"""Opportunity proposal team membership."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class MemberRole(models.TextChoices):
    OWNER = "OWNER", "Owner"
    COLLABORATOR = "COLLABORATOR", "Collaborator"


class InvitationStatus(models.TextChoices):
    INVITED = "INVITED", "Invited"
    ACCEPTED = "ACCEPTED", "Accepted"
    DECLINED = "DECLINED", "Declined"


class OpportunityMember(OrganizationOwnedModel):
    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        related_name="members",
    )
    user = models.ForeignKey(
        "identity.User",
        on_delete=models.PROTECT,
        related_name="opportunity_memberships",
    )
    member_role = models.CharField(max_length=20, choices=MemberRole.choices)
    invitation_status = models.CharField(
        max_length=20,
        choices=InvitationStatus.choices,
        default=InvitationStatus.INVITED,
    )
    active_from = models.DateTimeField()
    active_to = models.DateTimeField(null=True, blank=True)
    contribution_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opportunities_opportunity_member"
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "user", "member_role"],
                condition=models.Q(active_to__isnull=True),
                name="opportunities_member_active_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "member_role"]),
            models.Index(fields=["user", "invitation_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id}:{self.user_id}:{self.member_role}"
