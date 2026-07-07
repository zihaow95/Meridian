"""Download ticket issuance and consumption."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.documents.models import DocumentVersion, DownloadTicket, TicketAction
from apps.documents.storage.base import FileStorage
from apps.identity.models.user import User


class DownloadTicketExpired(Exception):
    pass


class DownloadTicketConsumed(Exception):
    pass


@dataclass(frozen=True)
class IssueDownloadTicket:
    actor: User
    version: DocumentVersion
    action: str = TicketAction.DOWNLOAD
    ttl_minutes: int = 5

    def execute(self) -> tuple[DownloadTicket, str]:
        token = secrets.token_urlsafe(32)
        ticket = DownloadTicket.objects.create(
            organization=self.actor.organization,
            user=self.actor,
            document_version=self.version,
            action=self.action,
            token_hash=_hash_token(token),
            expires_at=timezone.now() + timedelta(minutes=self.ttl_minutes),
        )
        return ticket, token


@dataclass(frozen=True)
class ConsumeDownloadTicket:
    token: str
    storage: FileStorage

    def execute(self) -> dict[str, str]:
        token_hash = _hash_token(self.token)
        with transaction.atomic():
            ticket = DownloadTicket.objects.select_for_update().get(token_hash=token_hash)
            if ticket.consumed_at is not None:
                raise DownloadTicketConsumed("Download ticket already used.")
            if ticket.expires_at <= timezone.now():
                raise DownloadTicketExpired("Download ticket expired.")
            ticket.consumed_at = timezone.now()
            ticket.save(update_fields=["consumed_at"])
            object_key = ticket.document_version.file_object.object_key
            return {
                "X-Accel-Redirect": self.storage.internal_redirect_header(object_key),
                "Content-Type": ticket.document_version.detected_mime_type,
            }


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
