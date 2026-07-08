"""Document upload API."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast
from uuid import UUID

from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.documents.models import UploadSession
from apps.documents.services.uploads import (
    CompleteUpload,
    CreateUploadSession,
    UploadValidationFailed,
)
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.api.permissions import requires_action

DocumentUploadPermission = requires_action(
    action_code="document.version.upload",
    resource_type="document.version",
)


class UploadSessionCreateView(APIView):
    permission_classes = [IsAuthenticated, DocumentUploadPermission]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request: Request) -> Response:
        user = cast(User, request.user)
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            raise ValidationFailedError(details={"file": ["This field is required."]})

        original_filename = request.data.get("original_filename") or uploaded_file.name
        declared_mime_type = (
            request.data.get("declared_mime_type") or uploaded_file.content_type or ""
        )

        storage = get_file_storage()
        try:
            session = CreateUploadSession(
                actor=user,
                original_filename=original_filename,
                declared_mime_type=declared_mime_type,
                storage=storage,
            ).execute()
        except UploadValidationFailed as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        temp_path = Path(session.temp_path)
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size_bytes = 0
        with temp_path.open("wb") as handle:
            for chunk in uploaded_file.chunks():
                handle.write(chunk)
                digest.update(chunk)
                size_bytes += len(chunk)

        session.size_bytes = size_bytes
        session.sha256 = digest.hexdigest()
        session.save(update_fields=["size_bytes", "sha256"])

        return Response(
            {
                "public_id": str(session.public_id),
                "original_filename": session.original_filename,
                "declared_mime_type": session.declared_mime_type,
                "size_bytes": session.size_bytes,
            },
            status=201,
        )


class UploadSessionCompleteView(APIView):
    permission_classes = [IsAuthenticated, DocumentUploadPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["public_id"]

    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        session = UploadSession.objects.filter(public_id=public_id).first()
        if session is None:
            raise ResourceNotFoundError()

        storage = get_file_storage()
        try:
            version = CompleteUpload(
                session_public_id=public_id,
                actor=user,
                storage=storage,
                document_code=request.data.get("document_code") or None,
                title=request.data.get("title") or None,
            ).execute()
        except UploadValidationFailed as exc:
            raise ValidationFailedError(message=str(exc)) from exc

        return Response(
            {
                "version_public_id": str(version.public_id),
                "document_public_id": str(version.document.public_id),
                "status": version.status,
            }
        )
