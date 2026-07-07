"""Download ticket security."""

from __future__ import annotations

import pytest

from apps.documents.models import DownloadTicket
from apps.documents.services.tickets import (
    ConsumeDownloadTicket,
    DownloadTicketConsumed,
    IssueDownloadTicket,
)
from apps.documents.services.uploads import complete_upload


@pytest.mark.django_db
def test_download_ticket_stores_only_hash(upload_session, file_storage, active_user) -> None:
    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    ticket, token = IssueDownloadTicket(actor=active_user, version=version).execute()
    assert ticket.token_hash
    assert token not in DownloadTicket.objects.values_list("token_hash", flat=True)
    assert len(ticket.token_hash) == 64


@pytest.mark.django_db
def test_download_ticket_single_use(upload_session, file_storage, active_user) -> None:
    version = complete_upload(
        upload_session.public_id,
        actor=active_user,
        storage=file_storage,
    )
    _, token = IssueDownloadTicket(actor=active_user, version=version).execute()
    headers = ConsumeDownloadTicket(token=token, storage=file_storage).execute()
    assert headers["X-Accel-Redirect"].startswith("/protected-files/")
    assert "/objects/" not in headers["X-Accel-Redirect"]
    with pytest.raises(DownloadTicketConsumed):
        ConsumeDownloadTicket(token=token, storage=file_storage).execute()
