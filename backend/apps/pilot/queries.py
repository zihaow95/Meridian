"""Read models for pilot batches and feedback."""

from __future__ import annotations

from uuid import UUID

from apps.pilot.models import PilotBatch, PilotFeedback, PilotParticipant


def get_batch(*, organization_id: int, public_id: UUID) -> PilotBatch | None:
    return (
        PilotBatch.objects.filter(organization_id=organization_id, public_id=public_id)
        .prefetch_related("participants")
        .first()
    )


def list_batches(*, organization_id: int) -> list[PilotBatch]:
    return list(
        PilotBatch.objects.filter(organization_id=organization_id).order_by("-created_at")
    )


def list_participants(*, batch: PilotBatch) -> list[PilotParticipant]:
    return list(batch.participants.select_related("user").order_by("id"))


def list_feedback(*, batch: PilotBatch) -> list[PilotFeedback]:
    return list(
        batch.feedback_items.select_related("reporter", "assignee", "accepted_by").order_by(
            "-created_at"
        )
    )


def get_feedback(*, organization_id: int, public_id: UUID) -> PilotFeedback | None:
    return (
        PilotFeedback.objects.select_related("batch", "reporter", "assignee", "accepted_by")
        .filter(organization_id=organization_id, public_id=public_id)
        .first()
    )
