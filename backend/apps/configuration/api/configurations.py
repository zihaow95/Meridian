"""Configuration read and publish API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.configuration.models import ConfigurationDefinition, ConfigurationVersion
from apps.configuration.services import ConfigurationValidationFailed, PublishVersion
from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.api.permissions import requires_action

ConfigReadPermission = requires_action(
    action_code="configuration.version.read",
    resource_type="configuration.version",
)
ConfigPublishPermission = requires_action(
    action_code="configuration.version.publish",
    resource_type="configuration.version",
)


class ConfigurationDefinitionListView(APIView):
    permission_classes = [IsAuthenticated, ConfigReadPermission]

    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        definitions = ConfigurationDefinition.objects.filter(
            organization_id=user.organization_id
        ).order_by("definition_code")
        return Response(
            [
                {
                    "definition_code": definition.definition_code,
                    "name": definition.name,
                    "description": definition.description,
                }
                for definition in definitions
            ]
        )


class ConfigurationVersionListView(APIView):
    permission_classes = [IsAuthenticated, ConfigReadPermission]

    def get(self, request: Request, definition_code: str) -> Response:
        user = cast(User, request.user)
        definition = ConfigurationDefinition.objects.filter(
            organization_id=user.organization_id,
            definition_code=definition_code,
        ).first()
        if definition is None:
            raise ResourceNotFoundError()

        versions = ConfigurationVersion.objects.filter(definition=definition).order_by(
            "-version_number"
        )
        return Response(
            [
                {
                    "public_id": str(version.public_id),
                    "version_number": version.version_number,
                    "status": version.status,
                    "published_at": (
                        version.published_at.isoformat() if version.published_at else None
                    ),
                }
                for version in versions
            ]
        )


class ConfigurationVersionPublishView(APIView):
    permission_classes = [IsAuthenticated, ConfigPublishPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        version = ConfigurationVersion.objects.filter(
            public_id=public_id,
            organization_id=user.organization_id,
        ).first()
        if version is None:
            raise ResourceNotFoundError()

        try:
            published = PublishVersion(version=version, actor=user).execute()
        except ConfigurationValidationFailed as exc:
            raise ValidationFailedError(details={"validation_errors": exc.errors}) from exc
        except ValueError as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        return Response(
            {
                "public_id": str(published.public_id),
                "status": published.status,
                "version_number": published.version_number,
            }
        )
