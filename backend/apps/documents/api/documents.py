"""Document version and download API."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from django.http import HttpResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.documents.models import Document, DocumentVersion
from apps.documents.services.tickets import (
    ConsumeDownloadTicket,
    DownloadTicketConsumed,
    DownloadTicketExpired,
    IssueDownloadTicket,
)
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.user import User
from apps.platform.api.errors import ResourceNotFoundError
from apps.platform.api.permissions import requires_action

DocumentDownloadPermission = requires_action(
    action_code="document.version.download",
    resource_type="document.version",
)


class DocumentVersionListView(APIView):
    permission_classes = [IsAuthenticated, DocumentDownloadPermission]

    def get(self, request: Request, document_public_id: UUID) -> Response:
        user = cast(User, request.user)
        document = Document.objects.filter(
            public_id=document_public_id,
            organization_id=user.organization_id,
        ).first()
        if document is None:
            raise ResourceNotFoundError()

        versions = DocumentVersion.objects.filter(document=document).order_by("-version_number")
        return Response(
            [
                {
                    "public_id": str(version.public_id),
                    "version_number": version.version_number,
                    "status": version.status,
                    "original_filename": version.original_filename,
                }
                for version in versions
            ]
        )


class DocumentVersionDownloadTicketView(APIView):
    permission_classes = [IsAuthenticated, DocumentDownloadPermission]

    def get_authorization_resource_public_id(self) -> UUID:
        return self.kwargs["version_public_id"]

    def post(self, request: Request, version_public_id: UUID) -> Response:
        user = cast(User, request.user)
        version = DocumentVersion.objects.filter(
            public_id=version_public_id,
            organization_id=user.organization_id,
        ).first()
        if version is None:
            raise ResourceNotFoundError()

        _, token = IssueDownloadTicket(actor=user, version=version).execute()
        return Response({"token": token})


class DocumentDownloadView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request, token: str) -> HttpResponse:
        storage = get_file_storage()
        try:
            headers = ConsumeDownloadTicket(token=token, storage=storage).execute()
        except (DownloadTicketExpired, DownloadTicketConsumed):
            raise ResourceNotFoundError() from None

        response = HttpResponse(status=200)
        for key, value in headers.items():
            response[key] = value
        return response
