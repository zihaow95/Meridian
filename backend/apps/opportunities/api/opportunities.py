"""Proposal lifecycle API: create, edit, invite, submit, withdraw, read."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.opportunities.models import (
    Opportunity,
    ProposalStatus,
    ProposalVersionStatus,
)
from apps.opportunities.queries.opportunities import (
    list_my_opportunities,
    list_versions,
    serialize_detail,
    serialize_public,
    serialize_summary,
)
from apps.opportunities.services.create_draft import CreateOpportunityDraft
from apps.opportunities.services.invite_member import InviteOpportunityMember
from apps.opportunities.services.submit_proposal import SubmitProposal
from apps.opportunities.services.withdraw_proposal import WithdrawProposal
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.application.command import CommandContext


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationFailedError(message="Invalid suggested_retail_price.") from exc


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError(message=f"Invalid {field}.") from exc


def _can(user: User, action: str, opportunity: Opportunity) -> bool:
    return authorize(
        subject_for(user),
        action=action,
        resource=ResourceDescriptor(
            resource_type="opportunity",
            public_id=opportunity.public_id,
            organization_id=opportunity.organization_id,
        ),
        context=AuthorizationContext.current(),
    ).allowed


class OpportunityCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="opportunities_list_mine")
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        opportunities = list_my_opportunities(user)
        return Response([serialize_summary(item) for item in opportunities])

    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        title = str(data.get("title", "")).strip()
        if not title:
            raise ValidationFailedError(message="title is required.")

        opportunity = CreateOpportunityDraft(
            context=CommandContext.for_actor(user),
            title=title,
            initial_type=str(data.get("initial_type", "UNDECIDED")),
            public_summary=str(data.get("public_summary", "")),
            quota_owner_type=str(data.get("quota_owner_type", "USER")),
            owner_department_id=data.get("owner_department_id"),
            market_analysis=str(data.get("market_analysis", "")),
            core_selling_points=str(data.get("core_selling_points", "")),
            target_users_needs=str(data.get("target_users_needs", "")),
            suggested_retail_price=_decimal_or_none(data.get("suggested_retail_price")),
        ).execute()
        return Response(serialize_detail(opportunity), status=201)


class OpportunityDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _load(self, user: User, public_id: UUID) -> Opportunity:
        opportunity = (
            Opportunity.objects.select_related("current_version")
            .filter(
                public_id=public_id,
                organization_id=user.organization_id,
            )
            .first()
        )
        if opportunity is None:
            raise ResourceNotFoundError()
        return opportunity

    @extend_schema(operation_id="opportunities_retrieve_detail")
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        opportunity = self._load(user, public_id)
        if _can(user, "opportunity.full.read", opportunity):
            return Response(serialize_detail(opportunity))
        if _can(user, "opportunity.public_summary.read", opportunity):
            return Response(serialize_public(opportunity))
        raise ResourceNotFoundError()

    def patch(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        opportunity = self._load(user, public_id)
        if not _can(user, "opportunity.edit", opportunity):
            raise ResourceNotFoundError()
        if opportunity.proposal_status not in {
            ProposalStatus.DRAFT,
            ProposalStatus.NEEDS_INFO,
        }:
            raise ValidationFailedError(message="Only draft proposals can be edited.")

        data = request.data
        if "title" in data:
            opportunity.title = str(data["title"]).strip()
        if "public_summary" in data:
            opportunity.public_summary = str(data["public_summary"])
        opportunity.save(update_fields=["title", "public_summary", "updated_at"])

        version = opportunity.current_version
        if version is not None and version.version_status == ProposalVersionStatus.DRAFT:
            for field in (
                "market_analysis",
                "core_selling_points",
                "target_users_needs",
            ):
                if field in data:
                    setattr(version, field, str(data[field]))
            if "suggested_retail_price" in data:
                version.suggested_retail_price = _decimal_or_none(data["suggested_retail_price"])
            version.save()

        return Response(serialize_detail(opportunity))


class OpportunityMemberInvitationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        invitee = _uuid(request.data.get("invitee_public_id"), "invitee_public_id")
        member = InviteOpportunityMember(
            context=CommandContext.for_actor(user),
            opportunity_public_id=public_id,
            invitee_public_id=invitee,
            contribution_note=str(request.data.get("contribution_note", "")),
        ).execute()
        return Response(
            {
                "public_id": str(member.public_id),
                "invitation_status": member.invitation_status,
            },
            status=201,
        )


class OpportunitySubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        version_no = request.data.get("version_no")
        opportunity = SubmitProposal(
            context=CommandContext.for_actor(user),
            opportunity_public_id=public_id,
            version_no=int(version_no) if version_no is not None else -1,
            idempotency_key=str(request.data.get("idempotency_key", "")),
        ).execute()
        return Response(serialize_summary(opportunity))


class OpportunityWithdrawView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        version_no = request.data.get("version_no")
        opportunity = WithdrawProposal(
            context=CommandContext.for_actor(user),
            opportunity_public_id=public_id,
            version_no=int(version_no) if version_no is not None else -1,
        ).execute()
        return Response(serialize_summary(opportunity))


class OpportunityVersionsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        opportunity = Opportunity.objects.filter(
            public_id=public_id,
            organization_id=user.organization_id,
        ).first()
        if opportunity is None:
            raise ResourceNotFoundError()
        if not _can(user, "opportunity.full.read", opportunity):
            raise ResourceNotFoundError()
        return Response(list_versions(opportunity))
