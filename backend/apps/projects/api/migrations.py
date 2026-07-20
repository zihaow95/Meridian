"""In-flight project migration batch APIs."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.documents.storage.factory import get_file_storage
from apps.identity.models.user import User
from apps.platform.api.errors import ValidationFailedError
from apps.platform.api.permissions import requires_action
from apps.platform.application.command import CommandContext
from apps.projects.errors import MigrationImportFailed
from apps.projects.models import MigrationDisposition
from apps.projects.services.confirm_migration_baseline import ConfirmMigrationBaseline
from apps.projects.services.import_migration_baseline import ImportProjectMigrationBatch
from apps.projects.services.stage_migration_file import StageMigrationFile

MigrationStagePermission = requires_action(
    action_code="project_migration.confirm",
    resource_type="project",
)

MIGRATION_BATCH_REQUEST = inline_serializer(
    name="MigrationBatchCreateRequest",
    fields={
        "batch_key": serializers.CharField(),
        "rows": serializers.ListField(child=serializers.DictField()),
    },
)

MIGRATION_BATCH_RESPONSE = inline_serializer(
    name="MigrationBatchCreateResponse",
    fields={
        "public_id": serializers.UUIDField(),
        "batch_key": serializers.CharField(),
        "accepted_count": serializers.IntegerField(),
        "error_count": serializers.IntegerField(),
        "row_errors": serializers.ListField(),
        "baselines": serializers.ListField(),
    },
)

MIGRATION_CONFIRM_REQUEST = inline_serializer(
    name="MigrationBaselineConfirmRequest",
    fields={
        "disposition": serializers.CharField(),
        "idempotency_key": serializers.CharField(),
    },
)

MIGRATION_CONFIRM_HISTORY_FILE = inline_serializer(
    name="MigrationBaselineConfirmHistoryFile",
    fields={
        "filename": serializers.CharField(),
        "document_version_public_id": serializers.UUIDField(allow_null=True, required=False),
        "sha256": serializers.CharField(required=False, allow_blank=True),
        "size_bytes": serializers.IntegerField(required=False),
    },
)

MIGRATION_CONFIRM_RESPONSE = inline_serializer(
    name="MigrationBaselineConfirmResponse",
    fields={
        "baseline_public_id": serializers.UUIDField(),
        "disposition": serializers.CharField(),
        "status": serializers.CharField(),
        "project_public_id": serializers.UUIDField(allow_null=True),
        "history_files": serializers.ListField(
            child=MIGRATION_CONFIRM_HISTORY_FILE,
            required=False,
        ),
    },
)


class ProjectMigrationFileStageView(APIView):
    """Stream a migration history file into tmp/migration before batch import."""

    permission_classes = [IsAuthenticated, MigrationStagePermission]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        operation_id="project_migration_files_stage",
        request=inline_serializer(
            name="MigrationFileStageRequest",
            fields={
                "file": serializers.FileField(),
                "filename": serializers.CharField(required=False),
                "mime_type": serializers.CharField(required=False),
            },
        ),
        responses={
            201: inline_serializer(
                name="MigrationFileStageResponse",
                fields={
                    "public_id": serializers.UUIDField(),
                    "filename": serializers.CharField(),
                    "mime_type": serializers.CharField(),
                    "sha256": serializers.CharField(),
                    "size_bytes": serializers.IntegerField(),
                    "staging_relpath": serializers.CharField(),
                    "expires_at": serializers.CharField(),
                },
            ),
        },
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise ValidationFailedError(details={"file": ["This field is required."]})
        filename = str(request.data.get("filename") or uploaded.name or "migrated-file")
        mime_type = str(
            request.data.get("mime_type") or uploaded.content_type or "application/octet-stream"
        )
        try:
            staged = StageMigrationFile(
                context=CommandContext.for_actor(user),
                chunks=uploaded.chunks(),
                filename=filename,
                mime_type=mime_type,
                storage=get_file_storage(),
            ).execute()
        except MigrationImportFailed as exc:
            raise ValidationFailedError(message=str(exc)) from exc
        return Response(staged, status=201)


class ProjectMigrationBatchCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_migration_batches_create",
        request=MIGRATION_BATCH_REQUEST,
        responses={201: MIGRATION_BATCH_RESPONSE},
    )
    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        batch_key = str(request.data.get("batch_key") or "").strip()
        rows = request.data.get("rows")
        if not batch_key:
            raise ValidationFailedError(message="batch_key is required.")
        if not isinstance(rows, list):
            raise ValidationFailedError(message="rows must be a list.")
        result = ImportProjectMigrationBatch(
            context=CommandContext.for_actor(user),
            batch_key=batch_key,
            rows=[dict(row) for row in rows],
        ).execute()
        return Response(
            {
                "public_id": str(result.batch.public_id),
                "batch_key": result.batch.batch_key,
                "accepted_count": result.accepted_count,
                "error_count": result.error_count,
                "row_errors": result.batch.row_errors,
                "baselines": [
                    {
                        "public_id": str(item.public_id),
                        "external_project_id": item.external_project_id,
                        "current_stage_code": item.current_stage_code,
                        "status": item.status,
                    }
                    for item in result.baselines
                ],
            },
            status=201,
        )


class ProjectMigrationBaselineConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_migration_baselines_confirm",
        request=MIGRATION_CONFIRM_REQUEST,
        responses={200: MIGRATION_CONFIRM_RESPONSE},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        disposition = str(request.data.get("disposition") or "").strip()
        idempotency_key = str(request.data.get("idempotency_key") or "").strip()
        if disposition not in MigrationDisposition.values:
            raise ValidationFailedError(message="disposition is invalid.")
        if not idempotency_key:
            raise ValidationFailedError(message="idempotency_key is required.")
        result = ConfirmMigrationBaseline(
            context=CommandContext.for_actor(user),
            baseline_public_id=public_id,
            disposition=disposition,
            idempotency_key=idempotency_key,
        ).execute()
        history_files = [
            {
                "filename": str(item.get("filename") or item.get("name") or "migrated-file"),
                "document_version_public_id": item.get("document_version_public_id"),
                "sha256": item.get("sha256"),
                "size_bytes": item.get("size_bytes"),
            }
            for item in list(result.baseline.history_files or [])
            if isinstance(item, dict)
        ]
        return Response(
            {
                "baseline_public_id": str(result.baseline.public_id),
                "disposition": result.baseline.disposition,
                "status": result.baseline.status,
                "project_public_id": str(result.project.public_id) if result.project else None,
                "history_files": history_files,
            }
        )
