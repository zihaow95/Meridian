"""Administrative grant and troubleshoot APIs."""

from __future__ import annotations

from typing import cast

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.queries.events import list_audit_events, serialize_audit_event
from apps.identity.models.user import User


class AuditEventsAdminView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        events = list_audit_events(user=user, limit=50)
        return Response([serialize_audit_event(event) for event in events])
