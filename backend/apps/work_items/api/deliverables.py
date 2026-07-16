"""Deliverable revision and confirmation APIs."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.work_items.services.deliverables import (
    CreateDeliverableRevision,
    SubmitRevisionForConfirmation,
)
from apps.work_items.services.professional_confirmations import DecideProfessionalConfirmation

REVISION_RESPONSE = inline_serializer(
    name="DeliverableRevisionResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "revision_number": serializers.IntegerField(required=False),
        "status": serializers.CharField(),
        "content_hash": serializers.CharField(required=False),
    },
)

CONFIRMATION_RESPONSE = inline_serializer(
    name="ProfessionalConfirmationResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "status": serializers.CharField(),
        "comment": serializers.CharField(required=False),
    },
)


REVISION_CREATE_REQUEST = inline_serializer(
    name="DeliverableRevisionCreateRequest",
    fields={"document_version_public_id": serializers.UUIDField()},
)

REVISION_SUBMIT_REQUEST = inline_serializer(
    name="DeliverableRevisionSubmitRequest",
    fields={"confirmer_public_id": serializers.UUIDField()},
)

CONFIRMATION_DECIDE_REQUEST = inline_serializer(
    name="ProfessionalConfirmationDecideRequest",
    fields={
        "decision": serializers.CharField(),
        "comment": serializers.CharField(required=False),
    },
)


class DeliverableRevisionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="deliverables_revisions_create",
        request=REVISION_CREATE_REQUEST,
        responses={201: REVISION_RESPONSE},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        document_version_public_id = request.data.get("document_version_public_id")
        if not document_version_public_id:
            raise ValidationFailedError(message="document_version_public_id is required.")
        revision = CreateDeliverableRevision(
            context=CommandContext.for_actor(user),
            deliverable_public_id=public_id,
            document_version_public_id=UUID(str(document_version_public_id)),
        ).execute()
        return Response(
            {
                "public_id": str(revision.public_id),
                "revision_number": revision.revision_number,
                "status": revision.status,
                "content_hash": revision.content_hash,
            },
            status=201,
        )


class DeliverableRevisionSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="deliverable_revisions_submit",
        request=REVISION_SUBMIT_REQUEST,
        responses={200: REVISION_RESPONSE},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        confirmer_public_id = request.data.get("confirmer_public_id")
        if not confirmer_public_id:
            raise ValidationFailedError(message="confirmer_public_id is required.")
        revision = SubmitRevisionForConfirmation(
            context=CommandContext.for_actor(user),
            revision_public_id=public_id,
            confirmer_public_id=UUID(str(confirmer_public_id)),
        ).execute()
        return Response(
            {
                "public_id": str(revision.public_id),
                "status": revision.status,
                "content_hash": revision.content_hash,
            }
        )


class ProfessionalConfirmationDecideView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="professional_confirmations_decide",
        request=CONFIRMATION_DECIDE_REQUEST,
        responses={200: CONFIRMATION_RESPONSE},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        decision = str(request.data.get("decision") or "")
        if not decision:
            raise ValidationFailedError(message="decision is required.")
        confirmation = DecideProfessionalConfirmation(
            context=CommandContext.for_actor(user),
            confirmation_public_id=public_id,
            decision=decision,
            comment=str(request.data.get("comment") or ""),
        ).execute()
        return Response(
            {
                "public_id": str(confirmation.public_id),
                "status": confirmation.status,
                "comment": confirmation.comment,
            }
        )
