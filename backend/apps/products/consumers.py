"""Products local outbox consumers for material confirmation side effects."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from apps.identity.models.user import User
from apps.notifications.models import TodoStatus
from apps.notifications.services.todos import SettleOneOpenTodo
from apps.platform.application.command import CommandContext
from apps.platform.outbox.consumer import OutboxConsumer
from apps.platform.outbox.models import OutboxEvent
from apps.products.models import MaterialConfirmation, MaterialConfirmationDecision
from apps.products.services.material_confirmations import confirmation_todo_dedup_key


class MaterialConfirmationEventRejected(Exception):
    """The event contradicts the stored confirmation, so nothing may be settled."""


def _matches(payload: dict[str, Any], key: str, expected: object) -> bool:
    """Compare a payload field against a database fact, if the field is present.

    Only an absent key means "written before this field existed" and falls back to
    the authoritative row. A key that is present but null asserts "no value", which
    a decided confirmation never has, so it is a defect like any other mismatch.
    """

    if key not in payload:
        return True
    if payload[key] is None:
        return False
    return str(payload[key]) == str(expected)


class MaterialConfirmationDecidedConsumer:
    """Settle the confirmation todo after the deciding transaction commits.

    Ordering matters more than immediacy here: `todo.requested` projects the todo
    after commit, so a decision taken inside the requesting transaction would
    otherwise settle nothing and leave an OPEN todo behind an APPROVED material.
    Retries can also arrive out of order, so a settlement whose todo does not
    exist yet stays retryable rather than claiming success.
    """

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "material_confirmation.decided":
            return
        payload = event.payload_json or {}
        if "confirmation_public_id" in payload and payload["confirmation_public_id"] is None:
            raise MaterialConfirmationEventRejected("confirmation_public_id must not be null")
        confirmation_id = UUID(str(payload.get("confirmation_public_id") or event.aggregate_id))
        confirmation = (
            MaterialConfirmation.objects.select_related("material")
            .filter(public_id=confirmation_id)
            .first()
        )
        if confirmation is None:
            raise MaterialConfirmationEventRejected(
                f"confirmation {confirmation_id} does not resolve"
            )
        # The stream this event belongs to must be the confirmation it settles,
        # otherwise a payload could borrow another aggregate's delivery slot.
        if str(event.aggregate_id) != str(confirmation.public_id):
            raise MaterialConfirmationEventRejected(
                f"aggregate {event.aggregate_id} disagrees with confirmation {confirmation_id}"
            )
        if confirmation.decision == MaterialConfirmationDecision.PENDING:
            raise MaterialConfirmationEventRejected(
                f"confirmation {confirmation_id} carries no decision to settle"
            )

        actor_id = payload.get("actor_user_id")
        actor = User.objects.filter(pk=actor_id).first() if actor_id else None
        if actor is None:
            raise MaterialConfirmationEventRejected("a resolvable actor_user_id is required")
        # Only the nominated confirmer decides, so only the confirmer may be
        # recorded as the person who closed the todo and its notices.
        if actor.organization_id != confirmation.organization_id:
            raise MaterialConfirmationEventRejected(
                f"actor {actor.pk} belongs to another organization"
            )
        if confirmation.confirmer_id != actor.pk:
            raise MaterialConfirmationEventRejected(
                f"actor {actor.pk} did not decide confirmation {confirmation_id}"
            )

        material = confirmation.material
        dedup_key = confirmation_todo_dedup_key(confirmation.public_id)
        for key, expected in (
            ("material_public_id", material.public_id),
            ("organization_id", confirmation.organization_id),
            ("decision", confirmation.decision),
            ("assignee_id", confirmation.confirmer_id),
            ("todo_dedup_key", dedup_key),
        ):
            if not _matches(payload, key, expected):
                raise MaterialConfirmationEventRejected(
                    f"event {key} disagrees with confirmation {confirmation_id}"
                )

        SettleOneOpenTodo(
            context=CommandContext.for_actor(actor, trace_id=str(event.event_id)),
            assignee_id=confirmation.confirmer_id,
            dedup_key=dedup_key,
            status=TodoStatus.COMPLETED,
            close_reason="SOURCE_COMPLETED",
        ).execute()


def local_consumer_registry() -> dict[str, list[tuple[str, OutboxConsumer]]]:
    return {
        "material_confirmation.decided": [
            ("material_confirmation_decided", MaterialConfirmationDecidedConsumer()),
        ],
    }
