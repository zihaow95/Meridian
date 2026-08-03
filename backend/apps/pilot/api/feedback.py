"""Pilot feedback HTTP endpoints."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.pilot.api.serializers import serialize_feedback
from apps.pilot.queries import get_batch, list_feedback
from apps.pilot.services.feedback import (
    AssignPilotFeedback,
    ClosePilotFeedback,
    OpenPilotFeedback,
    RetestPilotFeedback,
    StartFeedbackHandling,
    SubmitFeedbackRetest,
)
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.api.permissions import requires_action
from apps.platform.api.request_parsing import parse_request_bool
from apps.platform.application.command import CommandContext

FeedbackCreatePermission = requires_action(
    action_code="pilot.feedback.create",
    resource_type="pilot.feedback",
)
FeedbackReadPermission = requires_action(
    action_code="pilot.feedback.read",
    resource_type="pilot.feedback",
)
FeedbackAssignPermission = requires_action(
    action_code="pilot.feedback.assign",
    resource_type="pilot.feedback",
)
FeedbackHandlePermission = requires_action(
    action_code="pilot.feedback.handle",
    resource_type="pilot.feedback",
)
FeedbackRetestPermission = requires_action(
    action_code="pilot.feedback.retest",
    resource_type="pilot.feedback",
)
FeedbackClosePermission = requires_action(
    action_code="pilot.feedback.close",
    resource_type="pilot.feedback",
)


def _feedback_fields() -> dict[str, serializers.Field]:
    return {
        "public_id": serializers.UUIDField(),
        "batch_public_id": serializers.UUIDField(),
        "title": serializers.CharField(),
        "reproduction_summary": serializers.CharField(),
        "severity": serializers.CharField(allow_blank=True),
        "status": serializers.CharField(),
        "external_key": serializers.CharField(allow_blank=True),
        "evidence_document_version_public_id": serializers.UUIDField(allow_null=True),
        "assignee_public_id": serializers.UUIDField(allow_null=True),
        "target_version": serializers.CharField(allow_blank=True),
        "workaround": serializers.CharField(allow_blank=True),
        "accepted_by_public_id": serializers.UUIDField(allow_null=True),
        "acceptance_note": serializers.CharField(allow_blank=True),
        "close_reason": serializers.CharField(allow_blank=True),
        "retest_result": serializers.CharField(allow_blank=True),
        "version_no": serializers.IntegerField(),
    }


def _optional_uuid(raw: object | None) -> UUID | None:
    if raw in (None, ""):
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValidationFailedError(message="UUID field is invalid.") from exc


class PilotFeedbackListCreateView(APIView):
    def get_permissions(self) -> list[BasePermission]:
        if self.request.method == "POST":
            return [IsAuthenticated(), FeedbackCreatePermission()]
        return [IsAuthenticated(), FeedbackReadPermission()]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["batch_public_id"]

    @extend_schema(
        operation_id="pilot_feedback_list",
        responses=inline_serializer(
            name="PilotFeedbackList",
            fields={
                "items": serializers.ListField(
                    child=inline_serializer(name="PilotFeedbackItem", fields=_feedback_fields())
                )
            },
        ),
    )
    def get(self, request: Request, batch_public_id: UUID) -> Response:
        user = cast(User, request.user)
        batch = get_batch(organization_id=user.organization_id, public_id=batch_public_id)
        if batch is None:
            raise ResourceNotFoundError()
        return Response({"items": [serialize_feedback(f) for f in list_feedback(batch=batch)]})

    @extend_schema(
        operation_id="pilot_feedback_create",
        request=inline_serializer(
            name="PilotFeedbackCreateRequest",
            fields={
                "title": serializers.CharField(),
                "reproduction_summary": serializers.CharField(),
                "external_key": serializers.CharField(required=False),
                "evidence_document_version_public_id": serializers.UUIDField(required=False),
            },
        ),
        responses={
            201: inline_serializer(name="PilotFeedbackCreateResponse", fields=_feedback_fields())
        },
    )
    def post(self, request: Request, batch_public_id: UUID) -> Response:
        user = cast(User, request.user)
        try:
            title = str(request.data["title"])
            summary = str(request.data["reproduction_summary"])
        except KeyError as exc:
            raise ValidationFailedError(message=f"{exc.args[0]} is required.") from exc
        feedback = OpenPilotFeedback(
            context=CommandContext.for_actor(user),
            batch_public_id=batch_public_id,
            title=title,
            reproduction_summary=summary,
            external_key=str(request.data.get("external_key") or ""),
            evidence_document_version_public_id=_optional_uuid(
                request.data.get("evidence_document_version_public_id")
            ),
        ).execute()
        return Response(serialize_feedback(feedback), status=status.HTTP_201_CREATED)


class PilotFeedbackAssignView(APIView):
    permission_classes = [IsAuthenticated, FeedbackAssignPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_feedback_assign",
        request=inline_serializer(
            name="PilotFeedbackAssignRequest",
            fields={
                "severity": serializers.CharField(),
                "assignee_public_id": serializers.UUIDField(),
                "expected_version": serializers.IntegerField(required=False),
            },
        ),
        responses={
            200: inline_serializer(name="PilotFeedbackAssignResponse", fields=_feedback_fields())
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        try:
            severity = str(request.data["severity"])
            assignee_public_id = UUID(str(request.data["assignee_public_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValidationFailedError(
                message="severity and assignee_public_id are required."
            ) from exc
        expected = request.data.get("expected_version")
        feedback = AssignPilotFeedback(
            context=CommandContext.for_actor(user),
            feedback_public_id=public_id,
            severity=severity,
            assignee_public_id=assignee_public_id,
            expected_version=int(expected) if expected is not None else None,
        ).execute()
        return Response(serialize_feedback(feedback))


class PilotFeedbackHandleView(APIView):
    permission_classes = [IsAuthenticated, FeedbackHandlePermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_feedback_handle",
        request=inline_serializer(
            name="PilotFeedbackHandleRequest",
            fields={"expected_version": serializers.IntegerField(required=False)},
        ),
        responses={
            200: inline_serializer(name="PilotFeedbackHandleResponse", fields=_feedback_fields())
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        expected = request.data.get("expected_version")
        feedback = StartFeedbackHandling(
            context=CommandContext.for_actor(user),
            feedback_public_id=public_id,
            expected_version=int(expected) if expected is not None else None,
        ).execute()
        return Response(serialize_feedback(feedback))


class PilotFeedbackRetestSubmitView(APIView):
    permission_classes = [IsAuthenticated, FeedbackHandlePermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_feedback_submit_retest",
        request=inline_serializer(
            name="PilotFeedbackSubmitRetestRequest",
            fields={
                "target_version": serializers.CharField(required=False, allow_blank=True),
                "expected_version": serializers.IntegerField(required=False),
            },
        ),
        responses={
            200: inline_serializer(
                name="PilotFeedbackSubmitRetestResponse", fields=_feedback_fields()
            )
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        expected = request.data.get("expected_version")
        feedback = SubmitFeedbackRetest(
            context=CommandContext.for_actor(user),
            feedback_public_id=public_id,
            target_version=str(request.data.get("target_version") or ""),
            expected_version=int(expected) if expected is not None else None,
        ).execute()
        return Response(serialize_feedback(feedback))


class PilotFeedbackRetestView(APIView):
    permission_classes = [IsAuthenticated, FeedbackRetestPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_feedback_retest",
        request=inline_serializer(
            name="PilotFeedbackRetestRequest",
            fields={
                "passed": serializers.BooleanField(),
                "expected_version": serializers.IntegerField(required=False),
            },
        ),
        responses={
            200: inline_serializer(name="PilotFeedbackRetestResponse", fields=_feedback_fields())
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        if "passed" not in request.data:
            raise ValidationFailedError(message="passed is required.")
        expected = request.data.get("expected_version")
        feedback = RetestPilotFeedback(
            context=CommandContext.for_actor(user),
            feedback_public_id=public_id,
            passed=parse_request_bool(request.data["passed"], field="passed"),
            expected_version=int(expected) if expected is not None else None,
        ).execute()
        return Response(serialize_feedback(feedback))


class PilotFeedbackCloseView(APIView):
    permission_classes = [IsAuthenticated, FeedbackClosePermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="pilot_feedback_close",
        request=inline_serializer(
            name="PilotFeedbackCloseRequest",
            fields={
                "reject": serializers.BooleanField(required=False),
                "close_reason": serializers.CharField(required=False, allow_blank=True),
                "workaround": serializers.CharField(required=False, allow_blank=True),
                "target_version": serializers.CharField(required=False, allow_blank=True),
                "accepted_by_public_id": serializers.UUIDField(required=False),
                "acceptance_note": serializers.CharField(required=False, allow_blank=True),
                "expected_version": serializers.IntegerField(required=False),
            },
        ),
        responses={
            200: inline_serializer(name="PilotFeedbackCloseResponse", fields=_feedback_fields())
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        expected = request.data.get("expected_version")
        reject_raw = request.data.get("reject", False)
        feedback = ClosePilotFeedback(
            context=CommandContext.for_actor(user),
            feedback_public_id=public_id,
            reject=parse_request_bool(reject_raw, field="reject"),
            close_reason=str(request.data.get("close_reason") or ""),
            workaround=str(request.data.get("workaround") or ""),
            target_version=str(request.data.get("target_version") or ""),
            accepted_by_public_id=_optional_uuid(request.data.get("accepted_by_public_id")),
            acceptance_note=str(request.data.get("acceptance_note") or ""),
            expected_version=int(expected) if expected is not None else None,
        ).execute()
        return Response(serialize_feedback(feedback))
