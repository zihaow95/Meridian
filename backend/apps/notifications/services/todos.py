"""Todo projection from domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.notifications.models import Todo, TodoStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext


@dataclass(frozen=True)
class TodoEvent:
    assignee_id: int
    organization_id: int
    todo_type: str
    source_type: str
    source_id: UUID
    action_code: str
    dedup_key: str
    deep_link: str
    title: str
    due_at: datetime | None = None


@dataclass(frozen=True)
class UpsertOpenTodo:
    event: TodoEvent

    def execute(self) -> Todo:
        assignee = User.objects.get(pk=self.event.assignee_id)
        try:
            with transaction.atomic():
                return Todo.objects.create(
                    organization_id=self.event.organization_id,
                    assignee=assignee,
                    todo_type=self.event.todo_type,
                    source_type=self.event.source_type,
                    source_id=self.event.source_id,
                    action_code=self.event.action_code,
                    status=TodoStatus.OPEN,
                    due_at=self.event.due_at,
                    dedup_key=self.event.dedup_key,
                    deep_link=self.event.deep_link,
                    title=self.event.title,
                    open_slot=1,
                )
        except IntegrityError:
            return Todo.objects.get(
                assignee_id=self.event.assignee_id,
                dedup_key=self.event.dedup_key,
                status=TodoStatus.OPEN,
            )


def build_todo_event_from_outbox(payload: dict[str, Any]) -> TodoEvent:
    return TodoEvent(
        assignee_id=int(payload["assignee_id"]),
        organization_id=int(payload["organization_id"]),
        todo_type=str(payload["todo_type"]),
        source_type=str(payload["source_type"]),
        source_id=UUID(str(payload["source_id"])),
        action_code=str(payload["action_code"]),
        dedup_key=str(payload["dedup_key"]),
        deep_link=str(payload["deep_link"]),
        title=str(payload["title"]),
        due_at=None,
    )


@dataclass(frozen=True)
class SettleOpenTodosForSource:
    """Idempotently settle open todos and close their linked notifications.

    Completing, cancelling and expiring all release the open-dedup sentinel and
    close related notifications. A repeated settle must not reopen a closed
    notification or invent a new unread one.
    """

    organization_id: int
    source_type: str
    source_id: UUID
    status: str
    close_reason: str
    actor: User
    trace_id: str = ""

    def execute(self) -> int:
        from apps.notifications.services.lifecycle import SynchronizeNotificationForSource

        if self.actor is None:
            raise ValueError("SettleOpenTodosForSource requires an actor.")
        if self.status not in {
            TodoStatus.COMPLETED,
            TodoStatus.CANCELLED,
            TodoStatus.EXPIRED,
        }:
            raise ValueError(f"Cannot settle open todos into {self.status}.")

        with transaction.atomic():
            updated = Todo.objects.filter(
                organization_id=self.organization_id,
                source_type=self.source_type,
                source_id=self.source_id,
                status=TodoStatus.OPEN,
            ).update(status=self.status, open_slot=None)
            SynchronizeNotificationForSource(
                organization_id=self.organization_id,
                source_type=self.source_type,
                source_id=self.source_id,
                close_reason=self.close_reason,
                actor=self.actor,
                trace_id=self.trace_id,
            ).execute()
            return updated


# The domain row that owns the sensitivity a settle must respect, per todo source.
# Resolved through the app registry so a projection app does not depend on a domain
# app; a source that is not listed cannot be judged and is therefore refused.
_AUTHORITATIVE_SOURCES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "product_material": ("products", "ProductMaterial", ("material_type_code",)),
}


class TodoNotProjectedYet(Exception):
    """The todo this settlement targets has not been projected at all yet.

    Raised so the caller can stay retryable instead of recording a settlement
    that silently settled nothing.
    """


@dataclass(frozen=True)
class SettleOneOpenTodo:
    """Settle exactly the todo a dedup key names, with its own notifications.

    Settling by source would let a replayed or delayed event close a newer
    request for the same object. Settling by dedup key keeps each ask separate,
    and a missing todo is reported rather than treated as success.

    The actor is re-judged against the locked todo rather than trusted from the
    caller: a projection consumer reads whatever an event claims, so the right to
    settle has to be established here, in the same transaction as the write, and
    against the locked domain row rather than any sensitivity the caller supplies.

    Locks are taken source row first, todo second, because that is the order every
    domain path already uses - promoting a material and then cancelling its asks.
    Settling in the opposite order would deadlock against them under MySQL.
    """

    context: CommandContext
    assignee_id: int
    dedup_key: str
    status: str
    close_reason: str

    def execute(self) -> int:
        from apps.notifications.services.lifecycle import SynchronizeNotificationForTodo

        actor = self.context.actor
        if actor is None:
            raise ValueError("SettleOneOpenTodo requires an actor.")
        if self.status not in {
            TodoStatus.COMPLETED,
            TodoStatus.CANCELLED,
            TodoStatus.EXPIRED,
        }:
            raise ValueError(f"Cannot settle a todo into {self.status}.")

        with transaction.atomic():
            # Unlocked first, only to learn which source rows to lock ahead of the
            # todos. The locked read below is what the settle actually acts on.
            sources = sorted(
                {
                    (source_type, str(source_id))
                    for source_type, source_id in self._matching_todos().values_list(
                        "source_type", "source_id"
                    )
                }
            )
            if not sources:
                raise TodoNotProjectedYet(self.dedup_key)
            resources = {
                source: self._locked_source(source_type=source[0], source_id=UUID(source[1]))
                for source in sources
            }

            todos = list(self._matching_todos().select_for_update().order_by("pk"))
            if not todos:
                raise TodoNotProjectedYet(self.dedup_key)

            settled = 0
            for todo in todos:
                resource = resources.get((todo.source_type, str(todo.source_id)))
                if resource is None:
                    # A todo arrived after the sources were locked. Taking its source
                    # lock now would invert the order, so leave it to the next attempt.
                    raise TodoNotProjectedYet(self.dedup_key)
                self._require_may_act_on(todo, resource)
                if todo.status == TodoStatus.OPEN:
                    Todo.objects.filter(pk=todo.pk, status=TodoStatus.OPEN).update(
                        status=self.status, open_slot=None
                    )
                    settled += 1
                # Notices of an already-settled todo may still be open when an
                # earlier attempt died between the two writes.
                SynchronizeNotificationForTodo(
                    organization_id=todo.organization_id,
                    todo_id=todo.pk,
                    todo_public_id=todo.public_id,
                    actor=actor,
                    close_reason=self.close_reason,
                    trace_id=self.context.trace_id,
                ).execute()
            return settled

    def _matching_todos(self) -> QuerySet[Todo]:
        return Todo.objects.filter(
            organization_id=self.context.actor.organization_id,
            assignee_id=self.assignee_id,
            dedup_key=self.dedup_key,
        )

    def _require_may_act_on(self, todo: Todo, resource: ResourceDescriptor) -> None:
        """The settler must still hold the action the todo asks for."""

        decision = authorize(
            subject_for(self.context.actor),
            action=todo.action_code,
            resource=resource,
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()

    def _locked_source(self, *, source_type: str, source_id: UUID) -> ResourceDescriptor:
        """Read the sensitivity from the locked domain row, not from the caller.

        Whoever asked for this settlement read the source outside this transaction,
        so its sensitivity may already have been raised since. Locking and re-reading
        here closes the window where a settle is judged against a stale, lower level.
        """

        source = _AUTHORITATIVE_SOURCES.get(source_type)
        if source is None:
            raise PermissionDeniedError()
        app_label, model_name, metadata_fields = source
        model = django_apps.get_model(app_label, model_name)
        row = (
            model.objects.select_for_update()
            .filter(public_id=source_id, organization_id=self.context.actor.organization_id)
            .values("sensitivity_level", *metadata_fields)
            .first()
        )
        if row is None:
            raise PermissionDeniedError()
        return ResourceDescriptor(
            resource_type=source_type,
            public_id=source_id,
            organization_id=self.context.actor.organization_id,
            sensitivity_level=str(row["sensitivity_level"]),
            metadata={field: row[field] for field in metadata_fields},
        )


@dataclass(frozen=True)
class CompleteOpenTodosForSource:
    """Idempotently complete open todos that point at a domain source."""

    organization_id: int
    source_type: str
    source_id: UUID
    actor: User
    trace_id: str = ""

    def execute(self) -> int:
        return SettleOpenTodosForSource(
            organization_id=self.organization_id,
            source_type=self.source_type,
            source_id=self.source_id,
            status=TodoStatus.COMPLETED,
            close_reason="SOURCE_COMPLETED",
            actor=self.actor,
            trace_id=self.trace_id,
        ).execute()
