"""Proposal quota read API."""

from __future__ import annotations

from typing import cast

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.opportunities.api.schemas import CURRENT_PROPOSAL_QUOTA_SCHEMA
from apps.opportunities.queries.proposal_quotas import serialize_current_proposal_quota


class CurrentProposalQuotaView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="proposal_quotas_current_retrieve",
        responses=CURRENT_PROPOSAL_QUOTA_SCHEMA,
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        return Response(serialize_current_proposal_quota(user, as_of=timezone.now()))
