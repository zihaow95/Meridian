"""Deferred pool and quarterly review API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.opportunities.api.schemas import (
    DEFERRED_ITEM_SCHEMA,
    QUARTERLY_REVIEW_REQUEST_SCHEMA,
    QUARTERLY_REVIEW_RESPONSE_SCHEMA,
)
from apps.opportunities.models import DeferRecord
from apps.opportunities.services.quarterly_review import QuarterlyReview
from apps.platform.api.errors import ResourceNotFoundError
from apps.platform.application.command import CommandContext


class DeferredQuarterlyReviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="deferred_item_quarterly_review_create",
        request=QUARTERLY_REVIEW_REQUEST_SCHEMA,
        responses={200: QUARTERLY_REVIEW_RESPONSE_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        data = request.data
        entry = QuarterlyReview(
            context=CommandContext.for_actor(user),
            defer_record_public_id=public_id,
            action=str(data.get("action", "")),
            note=str(data.get("note", "")),
            new_restart_trigger=str(data.get("new_restart_trigger", "")),
            new_next_review_quarter=str(data.get("new_next_review_quarter", "")),
        ).execute()
        return Response(
            {
                "public_id": str(entry.public_id),
                "action": entry.action,
                "defer_record_public_id": str(entry.defer_record.public_id),
            }
        )


class DeferredItemDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="deferred_item_retrieve", responses=DEFERRED_ITEM_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        record = DeferRecord.objects.filter(
            public_id=public_id,
            organization_id=user.organization_id,
        ).first()
        if record is None:
            raise ResourceNotFoundError()
        return Response(
            {
                "public_id": str(record.public_id),
                "subject_type": record.subject_type,
                "subject_public_id": str(record.subject_public_id),
                "stage_code": record.stage_code,
                "defer_reason": record.defer_reason,
                "restart_trigger": record.restart_trigger,
                "next_review_quarter": record.next_review_quarter,
                "status": record.status,
            }
        )
