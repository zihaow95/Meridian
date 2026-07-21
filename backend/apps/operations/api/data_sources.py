"""Operating data source APIs."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.integrations.services.data_sources import (
    ConfigureOperatingDataSource,
    PublishOperatingDataSource,
)
from apps.operations.queries.visible_resources import list_visible_data_sources
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext

DATA_SOURCE_SCHEMA = inline_serializer(
    name="OperatingDataSource",
    fields={
        "public_id": serializers.UUIDField(),
        "source_code": serializers.CharField(),
        "name": serializers.CharField(),
        "source_type": serializers.CharField(),
        "status": serializers.CharField(),
        "sensitivity_level": serializers.CharField(),
        "owner_department_public_id": serializers.UUIDField(),
        "configuration_version_public_id": serializers.UUIDField(),
    },
)

DATA_SOURCE_CREATE_REQUEST = inline_serializer(
    name="OperatingDataSourceCreateRequest",
    fields={
        "source_code": serializers.CharField(),
        "name": serializers.CharField(),
        "source_type": serializers.CharField(),
        "owner_department_public_id": serializers.UUIDField(),
        "sensitivity_level": serializers.CharField(),
        "mapping_content": serializers.DictField(),
        "status": serializers.CharField(required=False),
    },
)


def serialize_data_source(source) -> dict[str, Any]:
    return {
        "public_id": str(source.public_id),
        "source_code": source.source_code,
        "name": source.name,
        "source_type": source.source_type,
        "status": source.status,
        "sensitivity_level": source.sensitivity_level,
        "owner_department_public_id": str(source.owner_department.public_id),
        "configuration_version_public_id": str(source.configuration_version.public_id),
    }


class OperatingDataSourceListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_sources_list",
        responses=inline_serializer(
            name="OperatingDataSourceListResponse",
            fields={"items": serializers.ListField(child=DATA_SOURCE_SCHEMA)},
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        items = [
            serialize_data_source(row)
            for row in list_visible_data_sources(user).select_related(
                "owner_department", "configuration_version"
            )
        ]
        return Response({"items": items})

    @extend_schema(
        operation_id="operating_data_sources_create",
        request=DATA_SOURCE_CREATE_REQUEST,
        responses={201: DATA_SOURCE_SCHEMA},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        data = request.data
        required = (
            "source_code",
            "name",
            "source_type",
            "owner_department_public_id",
            "sensitivity_level",
            "mapping_content",
        )
        missing = [key for key in required if not data.get(key)]
        if missing:
            raise ValidationFailedError(message=f"Missing fields: {', '.join(missing)}")
        source = ConfigureOperatingDataSource(
            context=CommandContext.for_actor(user),
            source_code=str(data["source_code"]),
            name=str(data["name"]),
            source_type=str(data["source_type"]),
            owner_department_public_id=UUID(str(data["owner_department_public_id"])),
            sensitivity_level=str(data["sensitivity_level"]),
            mapping_content=dict(data["mapping_content"]),
            status=str(data.get("status") or "ACTIVE"),
        ).execute()
        return Response(serialize_data_source(source), status=201)


class OperatingDataSourcePublishView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="operating_data_sources_publish",
        request=None,
        responses={200: DATA_SOURCE_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        source = PublishOperatingDataSource(
            context=CommandContext.for_actor(user),
            source_public_id=public_id,
        ).execute()
        return Response(serialize_data_source(source))
