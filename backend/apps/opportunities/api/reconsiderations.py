"""Reconsideration API for passed subjects."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.opportunities.services.start_reconsideration import StartReconsideration
from apps.platform.application.command import CommandContext


class ReconsiderationCollectionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        reconsideration = StartReconsideration(
            context=CommandContext.for_actor(user),
            original_subject_public_id=UUID(str(data["original_subject_public_id"])),
            target_stage_code=str(data.get("target_stage_code", "PROPOSAL_TO_CASE")),
            reason=str(data.get("reason", "")),
        ).execute()
        return Response(
            {
                "public_id": str(reconsideration.public_id),
                "original_cycle_public_id": str(reconsideration.original_cycle.public_id),
                "new_cycle_public_id": str(reconsideration.new_cycle.public_id),
                "target_stage_code": reconsideration.target_stage_code,
            },
            status=201,
        )
