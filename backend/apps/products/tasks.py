"""Async tasks for legacy product import processing."""

from __future__ import annotations

from uuid import UUID

from apps.platform.application.command import CommandContext
from apps.products.services.import_batch import CreateProductImportBatch


def parse_import_batch_task(
    *,
    actor_id: int,
    csv_content: str,
    source_filename: str,
) -> str:
    from apps.identity.models.user import User

    actor = User.objects.get(pk=actor_id)
    batch = CreateProductImportBatch(
        context=CommandContext.for_actor(actor),
        csv_content=csv_content,
        source_filename=source_filename,
    ).execute()
    return str(batch.public_id)


def parse_import_batch_by_id(*, batch_public_id: UUID, csv_content: str) -> None:
    del batch_public_id, csv_content
