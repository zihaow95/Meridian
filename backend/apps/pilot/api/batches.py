"""Pilot batch HTTP endpoints."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.pilot.api.serializers import serialize_batch, serialize_participant
from apps.pilot.queries import get_batch, list_batches, list_participants
from apps.pilot.services.batches import (
    AddPilotParticipant,
    CompletePilotBatch,
    CreatePilotBatch,
    StartPilotBatch,
)
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.api.permissions import requires_action
from apps.platform.application.command import CommandContext

BatchManagePermission = requires_action(
    action_code="pilot.batch.manage",
    resource_type="pilot.batch",
)
BatchReadPermission = requires_action(
    action_code="pilot.batch.read",
    resource_type="pilot.batch",
)

BATCH_FIELDS = {
    "public_id": serializers.UUIDField(),
    "name": serializers.CharField(),
    "purpose": serializers.CharField(),
    "status": serializers.CharField(),
    "planned_participant_count": serializers.IntegerField(),
    "planned_duration_days": serializers.IntegerField(),
    "config_snapshot": serializers.DictField(),
    "data_scope_note": serializers.CharField(),
    "feedback_owner_note": serializers.CharField(),
    "version_no": serializers.IntegerField(),
    "started_at": serializers.DateTimeField(allow_null=True),
    "completed_at": serializers.DateTimeField(allow_null=True),
}


class PilotBatchListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), BatchManagePermission()]
        return [IsAuthenticated(), BatchReadPermission()]

    @extend_schema(
        operation_id="pilot_batches_list",
        responses=inline_serializer(
            name="PilotBatchList",
            fields={"items": serializers.ListField(child=inline_serializer(
                name="PilotBatchItem", fields=BATCH_FIELDS
            ))},
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        items = [serialize_batch(b) for b in list_batches(organization_id=user.organization_id)]
        return Response({"items": items})

    @extend_schema(
        operation_id="pilot_batches_create",
        request=inline_serializer(
            name="PilotBatchCreateRequest",
            fields={
                "name": serializers.CharField(),
                "planned_participant_count": serializers.IntegerField(required=False),
                "planned_duration_days": serializers.IntegerField(required=False),
                "data_scope_note": serializers.CharField(required=False),
                "feedback_owner_note": serializers.CharField(required=False),
            },
        ),
        responses={201: inline_serializer(name="PilotBatchCreateResponse", fields=BATCH_FIELDS)},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        try:
            name = str(request.data["name"])
        except KeyError as exc:
            raise ValidationFailedError(message="name is required.") from exc
        batch = CreatePilotBatch(
            context=CommandContext.for_actor(user),
            name=name,
            planned_participant_count=int(
                request.data.get("planned_participant_count") or 8
            ),
            planned_duration_days=int(request.data.get("planned_duration_days") or 14),
            data_scope_note=str(request.data.get("data_scope_note") or ""),
            feedback_owner_note=str(request.data.get("feedback_owner_note") or ""),
        ).execute()
        return Response(serialize_batch(batch), status=status.HTTP_201_CREATED)


class PilotBatchDetailView(APIView):
    permission_classes = [IsAuthenticated, BatchReadPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_batches_retrieve",
        responses=inline_serializer(
            name="PilotBatchDetail",
            fields={
                **BATCH_FIELDS,
                "participants": serializers.ListField(
                    child=inline_serializer(
                        name="PilotParticipantItem",
                        fields={
                            "public_id": serializers.UUIDField(),
                            "user_public_id": serializers.UUIDField(),
                            "display_name_snapshot": serializers.CharField(),
                            "employee_no_snapshot": serializers.CharField(),
                            "department_snapshot": serializers.CharField(),
                            "role_codes_snapshot": serializers.ListField(
                                child=serializers.CharField()
                            ),
                        },
                    )
                ),
            },
        ),
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = get_batch(organization_id=user.organization_id, public_id=public_id)
        if batch is None:
            raise ResourceNotFoundError()
        payload = serialize_batch(batch)
        payload["participants"] = [
            serialize_participant(p) for p in list_participants(batch=batch)
        ]
        return Response(payload)


class PilotBatchParticipantView(APIView):
    permission_classes = [IsAuthenticated, BatchManagePermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_batches_add_participant",
        request=inline_serializer(
            name="PilotParticipantCreateRequest",
            fields={
                "user_public_id": serializers.UUIDField(),
                "department_snapshot": serializers.CharField(required=False),
            },
        ),
        responses={201: inline_serializer(
            name="PilotParticipantCreateResponse",
            fields={
                "public_id": serializers.UUIDField(),
                "user_public_id": serializers.UUIDField(),
                "display_name_snapshot": serializers.CharField(),
                "employee_no_snapshot": serializers.CharField(),
                "department_snapshot": serializers.CharField(),
                "role_codes_snapshot": serializers.ListField(child=serializers.CharField()),
            },
        )},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        try:
            user_public_id = UUID(str(request.data["user_public_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationFailedError(message="user_public_id is required.") from exc
        participant = AddPilotParticipant(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
            user_public_id=user_public_id,
            department_snapshot=str(request.data.get("department_snapshot") or ""),
        ).execute()
        return Response(serialize_participant(participant), status=status.HTTP_201_CREATED)


class PilotBatchStartView(APIView):
    permission_classes = [IsAuthenticated, BatchManagePermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_batches_start",
        request=None,
        responses={
            200: inline_serializer(name="PilotBatchStartResponse", fields=BATCH_FIELDS)
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = StartPilotBatch(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
        ).execute()
        return Response(serialize_batch(batch))


class PilotBatchCompleteView(APIView):
    permission_classes = [IsAuthenticated, BatchManagePermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_batches_complete",
        request=None,
        responses={
            200: inline_serializer(name="PilotBatchCompleteResponse", fields=BATCH_FIELDS)
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = CompletePilotBatch(
            context=CommandContext.for_actor(user),
            batch_public_id=public_id,
        ).execute()
        return Response(serialize_batch(batch))
