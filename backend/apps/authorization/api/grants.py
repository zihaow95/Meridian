"""Administrative grant and troubleshoot APIs."""

from __future__ import annotations

from typing import cast

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.queries.events import list_audit_events, serialize_audit_event
from apps.identity.models.user import User


class AuditEventsAdminView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="authorization_audit_events_list",
        responses=inline_serializer(
            name="AuditEventsAdminListItem",
            fields={
                "event_id": serializers.CharField(),
                "occurred_at": serializers.CharField(),
                "action_code": serializers.CharField(),
                "resource_type": serializers.CharField(),
                "resource_public_id": serializers.CharField(allow_null=True),
                "result": serializers.CharField(),
            },
            many=True,
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        events = list_audit_events(user=user, limit=50)
        return Response([serialize_audit_event(event) for event in events])
