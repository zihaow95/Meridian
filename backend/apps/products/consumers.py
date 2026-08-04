"""Products local outbox consumers for material confirmation side effects."""

from __future__ import annotations

from uuid import UUID

from apps.identity.models.user import User
from apps.notifications.services.todos import CompleteOpenTodosForSource
from apps.platform.outbox.consumer import OutboxConsumer
from apps.platform.outbox.models import OutboxEvent
from apps.products.models import MaterialConfirmation


class MaterialConfirmationDecidedConsumer:
    """Settle the confirmation todo after the deciding transaction commits.

    Ordering matters more than immediacy here: `todo.requested` projects the todo
    after commit, so a decision taken inside the requesting transaction would
    otherwise settle nothing and leave an OPEN todo behind an APPROVED material.
    """

    def consume(self, event: OutboxEvent) -> None:
        if event.event_type != "material_confirmation.decided":
            return
        payload = event.payload_json or {}
        confirmation_id = UUID(str(payload.get("confirmation_public_id") or event.aggregate_id))
        confirmation = (
            MaterialConfirmation.objects.select_related("material")
            .filter(public_id=confirmation_id)
            .first()
        )
        if confirmation is None:
            raise ValueError("material_confirmation.decided confirmation does not resolve")
        actor_id = payload.get("actor_user_id")
        actor = User.objects.filter(pk=actor_id).first() if actor_id else None
        if actor is None:
            raise ValueError("material_confirmation.decided requires a resolvable actor_user_id")
        CompleteOpenTodosForSource(
            organization_id=confirmation.organization_id,
            source_type="product_material",
            source_id=confirmation.material.public_id,
            actor=actor,
            trace_id=str(event.event_id),
        ).execute()


def local_consumer_registry() -> dict[str, list[tuple[str, OutboxConsumer]]]:
    return {
        "material_confirmation.decided": [
            ("material_confirmation_decided", MaterialConfirmationDecidedConsumer()),
        ],
    }
