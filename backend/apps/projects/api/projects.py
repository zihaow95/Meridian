"""Read-only project detail API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.opportunities.api.schemas import PROJECT_DETAIL_SCHEMA
from apps.platform.api.errors import ResourceNotFoundError
from apps.projects.models import Project
from apps.projects.queries.projects import serialize_project_detail


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="projects_retrieve", responses=PROJECT_DETAIL_SCHEMA)
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        project = (
            Project.objects.select_related(
                "candidate",
                "leader",
                "deputy_leader",
                "product_asset",
                "product_draft",
            )
            .filter(public_id=public_id, organization_id=user.organization_id)
            .first()
        )
        if project is None:
            raise ResourceNotFoundError()
        return Response(serialize_project_detail(project))
