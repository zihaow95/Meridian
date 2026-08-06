"""Configuration read and publish API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.admin_change import AdminChangeRequest, AdminChangeStatus
from apps.authorization.policies.engine import authorize
from apps.authorization.services.review_admin_change import (
    AdminChangeNotPending,
    ReviewerMustDiffer,
)
from apps.authorization.services.subject import subject_for
from apps.configuration.errors import (
    PublicationApprovalMissing,
    PublicationApprovalUnusable,
    PublicationRequestNotPending,
    PublicationReviewerMustDiffer,
    VersionNotPublishable,
)
from apps.configuration.models import ConfigurationDefinition, ConfigurationVersion
from apps.configuration.schema_registry import validate_content
from apps.configuration.services import (
    PUBLICATION_ACTION_TYPE,
    ConfigurationPublicationDenied,
    ConfigurationValidationFailed,
    ConfigurationVersionNotPublishable,
    CreateDraft,
    PublicationApprovalInvalid,
    PublicationApprovalRequired,
    PublishVersion,
    RequestConfigurationPublication,
    ReviewConfigurationPublication,
)
from apps.identity.models.user import User
from apps.platform.api.errors import (
    PermissionDeniedError,
    ResourceNotFoundError,
    ValidationFailedError,
)
from apps.platform.api.permissions import requires_action
from apps.platform.application.command import CommandContext

ConfigReadPermission = requires_action(
    action_code="configuration.version.read",
    resource_type="configuration.version",
)
ConfigPublishPermission = requires_action(
    action_code="configuration.version.publish",
    resource_type="configuration.version",
)
ConfigDraftPermission = requires_action(
    action_code="configuration.draft.create",
    resource_type="configuration.version",
)
ConfigPublicationRequestPermission = requires_action(
    action_code="configuration.publication.request",
    resource_type="configuration.version",
)
ConfigPublicationReviewPermission = requires_action(
    action_code="configuration.publication.review",
    resource_type="configuration.version",
)


def _may_read_sensitive_content(user: User) -> bool:
    decision = authorize(
        subject_for(user),
        action="configuration.content.read_sensitive",
        resource=ResourceDescriptor(
            resource_type="configuration.version",
            public_id=None,
            organization_id=user.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    return decision.allowed


def _approved_request_for(user: User, version: ConfigurationVersion) -> AdminChangeRequest | None:
    """Find the approval this publish attempt may consume, if one was granted."""
    return (
        AdminChangeRequest.objects.filter(
            action_type=PUBLICATION_ACTION_TYPE,
            status=AdminChangeStatus.APPROVED,
            proposed_by__organization_id=user.organization_id,
            target_summary__version_public_id=str(version.public_id),
        )
        .order_by("-reviewed_at")
        .first()
    )


def _version_for(user: User, public_id: UUID) -> ConfigurationVersion:
    version = (
        ConfigurationVersion.objects.select_related("definition")
        .filter(public_id=public_id, organization_id=user.organization_id)
        .first()
    )
    if version is None:
        raise ResourceNotFoundError()
    return version


class ConfigurationDefinitionListView(APIView):
    permission_classes = [IsAuthenticated, ConfigReadPermission]

    @extend_schema(
        operation_id="configuration_definitions_list",
        responses=inline_serializer(
            name="ConfigurationDefinitionListItem",
            fields={
                "definition_code": serializers.CharField(),
                "name": serializers.CharField(),
                "description": serializers.CharField(),
            },
            many=True,
        ),
    )
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

    @extend_schema(
        operation_id="configuration_versions_list",
        responses=inline_serializer(
            name="ConfigurationVersionListItem",
            fields={
                "public_id": serializers.CharField(),
                "version_number": serializers.IntegerField(),
                "status": serializers.CharField(),
                "published_at": serializers.CharField(allow_null=True),
            },
            many=True,
        ),
    )
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


class ConfigurationDraftCreateView(APIView):
    permission_classes = [IsAuthenticated, ConfigDraftPermission]

    @extend_schema(
        operation_id="configuration_drafts_create",
        request=inline_serializer(
            name="ConfigurationDraftCreateRequest",
            fields={
                "content": serializers.JSONField(),
                "scope": serializers.JSONField(required=False),
            },
        ),
        responses=inline_serializer(
            name="ConfigurationDraftCreateResponse",
            fields={
                "public_id": serializers.CharField(),
                "version_number": serializers.IntegerField(),
                "status": serializers.CharField(),
            },
        ),
    )
    def post(self, request: Request, definition_code: str) -> Response:
        user = cast(User, request.user)
        definition = ConfigurationDefinition.objects.filter(
            organization_id=user.organization_id,
            definition_code=definition_code,
        ).first()
        if definition is None:
            raise ResourceNotFoundError()

        content = request.data.get("content")
        if not isinstance(content, dict):
            raise ValidationFailedError(message="A configuration draft requires object content.")

        errors = validate_content(definition_code, content)
        if errors:
            raise ValidationFailedError(details={"validation_errors": errors})

        draft = CreateDraft(
            actor=user,
            definition=definition,
            content=content,
            scope=request.data.get("scope"),
        ).execute()
        return Response(
            {
                "public_id": str(draft.public_id),
                "version_number": draft.version_number,
                "status": draft.status,
            },
            status=201,
        )


class ConfigurationVersionDetailView(APIView):
    permission_classes = [IsAuthenticated, ConfigReadPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="configuration_versions_retrieve",
        responses=inline_serializer(
            name="ConfigurationVersionDetail",
            fields={
                "public_id": serializers.CharField(),
                "definition_code": serializers.CharField(),
                "version_number": serializers.IntegerField(),
                "status": serializers.CharField(),
                "content_digest": serializers.CharField(),
                "content_json": serializers.JSONField(allow_null=True),
                "validation_errors": serializers.ListField(child=serializers.CharField()),
                "diff_summary": serializers.JSONField(),
            },
        ),
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        version = _version_for(user, public_id)
        return Response(
            {
                "public_id": str(version.public_id),
                "definition_code": version.definition.definition_code,
                "version_number": version.version_number,
                "status": version.status,
                "content_digest": version.content_digest,
                "content_json": (
                    version.content_json if _may_read_sensitive_content(user) else None
                ),
                "validation_errors": version.validation_errors,
                "diff_summary": version.diff_summary,
            }
        )


class ConfigurationPublicationRequestCreateView(APIView):
    permission_classes = [IsAuthenticated, ConfigPublicationRequestPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="configuration_publication_requests_create",
        request=None,
        responses=inline_serializer(
            name="ConfigurationPublicationRequestResponse",
            fields={
                "public_id": serializers.CharField(),
                "status": serializers.CharField(),
                "version_public_id": serializers.CharField(),
            },
        ),
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        version = _version_for(user, public_id)
        try:
            change_request = RequestConfigurationPublication(
                context=CommandContext.for_actor(user),
                version_public_id=version.public_id,
            ).execute()
        except ConfigurationPublicationDenied as exc:
            raise PermissionDeniedError() from exc
        except ValueError as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        return Response(
            {
                "public_id": str(change_request.public_id),
                "status": change_request.status,
                "version_public_id": str(version.public_id),
            },
            status=201,
        )


class ConfigurationPublicationRequestListView(APIView):
    permission_classes = [IsAuthenticated, ConfigReadPermission]

    @extend_schema(
        operation_id="configuration_publication_requests_list",
        responses=inline_serializer(
            name="ConfigurationPublicationRequestListItem",
            fields={
                "public_id": serializers.CharField(),
                "definition_code": serializers.CharField(),
                "version_public_id": serializers.CharField(),
                "version_number": serializers.IntegerField(),
                "proposed_by": serializers.CharField(),
                "status": serializers.CharField(),
                "expires_at": serializers.CharField(),
            },
            many=True,
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        pending = (
            AdminChangeRequest.objects.select_related("proposed_by")
            .filter(
                action_type=PUBLICATION_ACTION_TYPE,
                status=AdminChangeStatus.PENDING,
                proposed_by__organization_id=user.organization_id,
            )
            .order_by("-created_at")
        )
        return Response(
            [
                {
                    "public_id": str(row.public_id),
                    "definition_code": row.target_summary.get("definition_code", ""),
                    "version_public_id": row.target_summary.get("version_public_id", ""),
                    "version_number": row.target_summary.get("version_number"),
                    "proposed_by": str(row.proposed_by.public_id),
                    "status": row.status,
                    "expires_at": row.expires_at.isoformat(),
                }
                for row in pending
            ]
        )


class ConfigurationPublicationReviewView(APIView):
    permission_classes = [IsAuthenticated, ConfigPublicationReviewPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="configuration_publication_requests_review",
        request=inline_serializer(
            name="ConfigurationPublicationReviewRequest",
            fields={"decision": serializers.CharField()},
        ),
        responses=inline_serializer(
            name="ConfigurationPublicationReviewResponse",
            fields={
                "public_id": serializers.CharField(),
                "status": serializers.CharField(),
            },
        ),
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        decision = request.data.get("decision")
        if decision not in {AdminChangeStatus.APPROVED, AdminChangeStatus.REJECTED}:
            raise ValidationFailedError(message="A review decision must be APPROVED or REJECTED.")

        if not AdminChangeRequest.objects.filter(
            public_id=public_id,
            action_type=PUBLICATION_ACTION_TYPE,
            proposed_by__organization_id=user.organization_id,
        ).exists():
            raise ResourceNotFoundError()

        try:
            reviewed = ReviewConfigurationPublication(
                context=CommandContext.for_actor(user),
                request_public_id=public_id,
                decision=decision,
            ).execute()
        except ReviewerMustDiffer as exc:
            raise PublicationReviewerMustDiffer() from exc
        except AdminChangeNotPending as exc:
            raise PublicationRequestNotPending() from exc
        except ConfigurationPublicationDenied as exc:
            raise PermissionDeniedError() from exc

        return Response({"public_id": str(reviewed.public_id), "status": reviewed.status})


class ConfigurationVersionPublishView(APIView):
    permission_classes = [IsAuthenticated, ConfigPublishPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    @extend_schema(
        operation_id="configuration_versions_publish",
        request=None,
        responses=inline_serializer(
            name="ConfigurationVersionPublishResponse",
            fields={
                "public_id": serializers.CharField(),
                "status": serializers.CharField(),
                "version_number": serializers.IntegerField(),
            },
        ),
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        version = _version_for(user, public_id)

        try:
            published = PublishVersion(
                version=version,
                actor=user,
                approved_request=_approved_request_for(user, version),
            ).execute()
        except PublicationApprovalRequired as exc:
            raise PublicationApprovalMissing() from exc
        except PublicationApprovalInvalid as exc:
            raise PublicationApprovalUnusable(message=str(exc)) from exc
        except ConfigurationVersionNotPublishable as exc:
            raise VersionNotPublishable(message=str(exc)) from exc
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
