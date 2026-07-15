"""In-flight project migration batch APIs."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.projects.models import MigrationDisposition
from apps.projects.services.confirm_migration_baseline import ConfirmMigrationBaseline
from apps.projects.services.import_migration_baseline import ImportProjectMigrationBatch


class ProjectMigrationBatchCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="project_migration_batches_create")
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

    @extend_schema(operation_id="project_migration_baselines_confirm")
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
        return Response(
            {
                "baseline_public_id": str(result.baseline.public_id),
                "disposition": result.baseline.disposition,
                "status": result.baseline.status,
                "project_public_id": (
                    str(result.project.public_id) if result.project is not None else None
                ),
            }
        )
