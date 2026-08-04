"""Material confirmations are their own record, and only one may be live.

Professional confirmation used to have nowhere to live: `ProductMaterial`
carried a nullable FK to `AttributeConfirmation`, which records a decision about
an attribute group's content hash, not about a file. A row there could never
prove that anybody looked at the bytes, so it cannot be replayed as an approval.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import (
    NOTIFICATION_DELIVERY_POLICY_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
)
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    AttributeOwnerType,
    MaterialConfirmation,
    MaterialConfirmationDecision,
    MaterialConfirmationSettlementRepair,
    MaterialStatus,
    ProductMaterial,
)
from apps.products.services.material_chains import make_material_current
from apps.products.services.material_confirmations import (
    DecideMaterialConfirmation,
    MaterialConfirmationRejected,
    SubmitMaterialConfirmation,
)

governed_materials = importlib.import_module(
    "apps.products.migrations.0013_governed_product_materials"
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _publish_todo_notification_catalog(organization, active_user) -> None:
    """Material confirmation emits todo.requested → in-app notification."""

    for code, content in (
        (
            NOTIFICATION_TEMPLATE_CATALOG_CODE,
            {
                "templates": [
                    {
                        "template_code": "todo.created",
                        "category": "ACTION_REQUIRED",
                        "default_level": "IMPORTANT",
                        "summary_template": "待办 {title} 需要处理",
                        "allowed_variables": ["title"],
                    }
                ]
            },
        ),
        (
            NOTIFICATION_DELIVERY_POLICY_CODE,
            {
                "rules": [
                    {
                        "category": "ACTION_REQUIRED",
                        "level": "IMPORTANT",
                        "channels": ["IN_APP"],
                    }
                ]
            },
        ),
    ):
        definition, _ = ConfigurationDefinition.objects.get_or_create(
            organization=organization,
            definition_code=code,
            defaults={"name": code, "description": ""},
        )
        ConfigurationVersion.objects.filter(
            definition=definition, status=ConfigurationStatus.PUBLISHED
        ).update(status=ConfigurationStatus.RETIRED, current_published_slot=None)
        ConfigurationVersion.objects.create(
            organization=organization,
            definition=definition,
            version_number=ConfigurationVersion.objects.filter(definition=definition).count() + 1,
            status=ConfigurationStatus.PUBLISHED,
            current_published_slot=1,
            content_json=content,
            created_by=active_user,
            published_at=timezone.now(),
        )


@pytest.fixture
def material(organization, change_set, controlled_document_version) -> ProductMaterial:
    return ProductMaterial.objects.create(
        organization=organization,
        change_set=change_set,
        owner_type="PRODUCT",
        owner_id=change_set.product_id,
        material_type_code="LABEL",
        document_version=controlled_document_version(),
    )


def live_confirmation(material: ProductMaterial, **overrides) -> MaterialConfirmation:
    defaults = {
        "organization": material.organization,
        "material": material,
        "document_version": material.document_version,
        "content_hash": material.document_version.file_object.sha256,
        "requested_by": material.change_set.created_by,
        "requested_at": timezone.now(),
    }
    return MaterialConfirmation.objects.create(**{**defaults, **overrides})


def test_a_pending_confirmation_occupies_the_material_live_slot(material) -> None:
    confirmation = live_confirmation(material)

    assert confirmation.decision == MaterialConfirmationDecision.PENDING
    assert confirmation.live_slot == 1
    assert confirmation.decided_at is None
    assert confirmation.confirmer is None


def test_database_refuses_a_second_live_confirmation_for_one_material(material) -> None:
    live_confirmation(material)

    with pytest.raises(IntegrityError), transaction.atomic():
        live_confirmation(material)


def test_a_returned_confirmation_releases_the_slot_for_a_new_request(material, active_user) -> None:
    returned = live_confirmation(material)
    returned.decision = MaterialConfirmationDecision.RETURNED
    returned.confirmer = active_user
    returned.decided_at = timezone.now()
    returned.live_slot = None
    returned.save()

    replacement = live_confirmation(material)

    assert replacement.live_slot == 1


def test_a_superseded_approval_releases_the_slot(material, active_user) -> None:
    approved = live_confirmation(
        material,
        decision=MaterialConfirmationDecision.APPROVED,
        confirmer=active_user,
        decided_at=timezone.now(),
    )
    assert approved.live_slot == 1

    approved.superseded_at = timezone.now()
    approved.live_slot = None
    approved.save()

    assert live_confirmation(material).live_slot == 1


def test_the_confirmation_records_the_exact_bytes_that_were_reviewed(material) -> None:
    confirmation = live_confirmation(material)

    assert confirmation.document_version_id == material.document_version_id
    assert confirmation.content_hash == material.document_version.file_object.sha256


def test_the_migration_never_replays_an_attribute_confirmation_as_an_approval() -> None:
    """An attribute-group decision is not evidence anybody reviewed a file."""

    with pytest.raises(RuntimeError) as excinfo:
        governed_materials.assert_legacy_material_confirmations_are_absent(linked_count=3)

    message = str(excinfo.value)
    assert "3" in message
    assert "products_material_confirmation" in message


def test_the_migration_proceeds_when_no_material_ever_carried_a_confirmation() -> None:
    governed_materials.assert_legacy_material_confirmations_are_absent(linked_count=0)


@pytest.fixture
def requester(active_user, grant_action) -> Any:
    grant_action(active_user, "product_material.manage", "product_material")
    return active_user


@pytest.fixture
def confirmer(another_active_user, grant_action) -> Any:
    grant_action(another_active_user, "product_material.confirm", "product_material")
    return another_active_user


@pytest.fixture
def current_material(organization, change_set, controlled_document_version) -> ProductMaterial:
    return ProductMaterial.objects.create(
        organization=organization,
        change_set=change_set,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=change_set.product_id,
        material_type_code="PRODUCT_LABEL",
        document_version=controlled_document_version(),
        version_no=1,
        current_slot=1,
    )


def submit(actor, material: ProductMaterial, confirmer) -> MaterialConfirmation:
    return SubmitMaterialConfirmation(
        context=CommandContext.for_actor(actor),
        material_public_id=material.public_id,
        confirmer_public_id=confirmer.public_id,
        comment="请确认标签版本",
    ).execute()


def decide(actor, confirmation: MaterialConfirmation, decision: str) -> MaterialConfirmation:
    return DecideMaterialConfirmation(
        context=CommandContext.for_actor(actor),
        confirmation_public_id=confirmation.public_id,
        decision=decision,
        comment="内容与备案一致",
    ).execute()


def test_a_request_names_the_confirmer_and_the_exact_file(
    requester, confirmer, current_material
) -> None:
    confirmation = submit(requester, current_material, confirmer)

    assert confirmation.confirmer_id == confirmer.id
    assert confirmation.decision == MaterialConfirmationDecision.PENDING
    assert confirmation.document_version_id == current_material.document_version_id
    assert confirmation.content_hash == current_material.document_version.file_object.sha256


def test_a_nominee_without_the_confirm_action_is_refused_at_request_time(
    requester, another_active_user, current_material
) -> None:
    with pytest.raises(MaterialConfirmationRejected):
        submit(requester, current_material, another_active_user)

    assert MaterialConfirmation.objects.count() == 0


def test_requesting_confirmation_requires_the_manage_action(
    another_active_user, confirmer, current_material
) -> None:
    with pytest.raises(PermissionDeniedError):
        submit(another_active_user, current_material, confirmer)


def test_a_superseded_material_cannot_be_sent_for_confirmation(
    requester, confirmer, current_material, organization, change_set, controlled_document_version
) -> None:
    old = ProductMaterial.objects.create(
        organization=organization,
        change_set=change_set,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=change_set.product_id,
        material_type_code="PRODUCT_LABEL",
        document_version=controlled_document_version(),
        version_no=2,
        current_slot=None,
    )

    with pytest.raises(MaterialConfirmationRejected):
        submit(requester, old, confirmer)


def test_only_the_nominated_confirmer_may_decide(
    requester, confirmer, current_material, grant_action, organization
) -> None:
    other = User.objects.create_user(
        organization=organization,
        display_name="Other confirmer",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(other, "product_material.confirm", "product_material")
    confirmation = submit(requester, current_material, confirmer)

    with pytest.raises(PermissionDeniedError):
        decide(other, confirmation, MaterialConfirmationDecision.APPROVED)

    confirmation.refresh_from_db()
    assert confirmation.decision == MaterialConfirmationDecision.PENDING


def test_an_approval_marks_the_material_approved(requester, confirmer, current_material) -> None:
    confirmation = submit(requester, current_material, confirmer)

    decided = decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    current_material.refresh_from_db()
    assert decided.decision == MaterialConfirmationDecision.APPROVED
    assert decided.decided_at is not None
    assert decided.live_slot == 1
    assert current_material.material_status == MaterialStatus.APPROVED


def test_a_return_leaves_the_material_unapproved_and_reopens_the_slot(
    requester, confirmer, current_material
) -> None:
    confirmation = submit(requester, current_material, confirmer)

    returned = decide(confirmer, confirmation, MaterialConfirmationDecision.RETURNED)

    current_material.refresh_from_db()
    assert returned.live_slot is None
    assert current_material.material_status == MaterialStatus.DRAFT

    replacement = submit(requester, current_material, confirmer)
    assert replacement.live_slot == 1


def test_a_decided_confirmation_cannot_be_decided_again(
    requester, confirmer, current_material
) -> None:
    confirmation = submit(requester, current_material, confirmer)
    decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    with pytest.raises(MaterialConfirmationRejected):
        decide(confirmer, confirmation, MaterialConfirmationDecision.RETURNED)


def test_a_second_live_request_for_one_material_is_refused_by_the_service(
    requester, confirmer, current_material
) -> None:
    submit(requester, current_material, confirmer)

    with pytest.raises(MaterialConfirmationRejected):
        submit(requester, current_material, confirmer)


def test_replacing_the_file_invalidates_the_approval_but_keeps_the_record(
    requester, confirmer, current_material, organization, controlled_document_version
) -> None:
    confirmation = submit(requester, current_material, confirmer)
    decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    newer = ProductMaterial.objects.create(
        organization=organization,
        change_set=current_material.change_set,
        owner_type=current_material.owner_type,
        owner_id=current_material.owner_id,
        material_type_code=current_material.material_type_code,
        document_version=controlled_document_version(content=b"%PDF-1.4 newer"),
        version_no=2,
        supersedes_material=current_material,
    )
    make_material_current(newer, context=CommandContext.for_actor(requester))

    confirmation.refresh_from_db()
    current_material.refresh_from_db()
    assert confirmation.superseded_at is not None
    assert confirmation.live_slot is None
    assert confirmation.decision == MaterialConfirmationDecision.APPROVED
    assert current_material.material_status == MaterialStatus.INACTIVE
    assert current_material.current_slot is None
    assert newer.current_slot == 1


def test_standing_down_a_material_closes_open_confirmation_todos_and_notifications(
    django_capture_on_commit_callbacks,
    requester,
    confirmer,
    current_material,
    organization,
    controlled_document_version,
) -> None:
    from apps.audit.models import AuditEvent
    from apps.notifications.models import Notification, NotificationStatus, Todo, TodoStatus
    from apps.platform.outbox.models import OutboxEvent

    with django_capture_on_commit_callbacks(execute=True):
        confirmation = submit(requester, current_material, confirmer)

    todo = Todo.objects.get(
        source_type="product_material",
        source_id=current_material.public_id,
        status=TodoStatus.OPEN,
    )
    notification = Notification.objects.get(todo=todo)
    assert notification.status == NotificationStatus.UNREAD

    newer = ProductMaterial.objects.create(
        organization=organization,
        change_set=current_material.change_set,
        owner_type=current_material.owner_type,
        owner_id=current_material.owner_id,
        material_type_code=current_material.material_type_code,
        document_version=controlled_document_version(content=b"%PDF-1.4 successor"),
        version_no=2,
        supersedes_material=current_material,
    )
    make_material_current(newer, context=CommandContext.for_actor(requester))

    confirmation.refresh_from_db()
    todo.refresh_from_db()
    notification.refresh_from_db()
    assert confirmation.superseded_at is not None
    assert todo.status == TodoStatus.CANCELLED
    assert todo.open_slot is None
    assert notification.status == NotificationStatus.CLOSED
    assert notification.close_reason == "MATERIAL_SUPERSEDED"
    assert AuditEvent.objects.filter(
        action_code="product_material.confirmation_supersede",
        resource_public_id=current_material.public_id,
        actor_user=requester,
    ).exists()
    assert OutboxEvent.objects.filter(
        event_type="material_confirmation.superseded",
        aggregate_id=current_material.public_id,
    ).exists()


def test_deciding_inside_the_requesting_transaction_still_settles_the_todo(
    django_capture_on_commit_callbacks, requester, confirmer, current_material
) -> None:
    """Seeds and importers request and decide inside one boundary.

    `todo.requested` only projects after commit, so a settle that ran inside the
    transaction would leave an OPEN todo and UNREAD notice behind an APPROVED
    material.
    """

    from apps.notifications.models import Notification, NotificationStatus, Todo, TodoStatus

    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            confirmation = submit(requester, current_material, confirmer)
            decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    current_material.refresh_from_db()
    assert current_material.material_status == MaterialStatus.APPROVED
    todo = Todo.objects.get(
        source_type="product_material",
        source_id=current_material.public_id,
    )
    assert todo.status == TodoStatus.COMPLETED
    assert todo.open_slot is None
    notification = Notification.objects.get(todo=todo)
    assert notification.status == NotificationStatus.CLOSED


def test_a_decision_that_reaches_the_consumer_before_its_todo_stays_retryable(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """Retries arrive in any order, so the settlement must converge in any order.

    A settlement that "succeeds" by settling nothing would take its receipt and
    never run again, and the recovered request projection would then leave an
    OPEN todo behind an APPROVED material forever.
    """

    from apps.notifications import consumers as notification_consumers
    from apps.notifications.models import Notification, NotificationStatus, Todo, TodoStatus
    from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent, OutboxStatus
    from apps.platform.outbox.tasks import LocalOutboxPublisher

    def _boom(self: Any, event: Any) -> None:
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(notification_consumers.TodoProjectionConsumer, "consume", _boom)
    with django_capture_on_commit_callbacks(execute=True):
        confirmation = submit(requester, current_material, confirmer)
    assert not Todo.objects.filter(source_id=current_material.public_id).exists()
    request_event = OutboxEvent.objects.get(
        event_type="todo.requested",
        aggregate_id=confirmation.public_id,
    )
    assert request_event.status == OutboxStatus.PENDING

    with django_capture_on_commit_callbacks(execute=True):
        decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    decided_event = OutboxEvent.objects.get(
        event_type="material_confirmation.decided",
        aggregate_id=confirmation.public_id,
    )
    assert decided_event.status == OutboxStatus.PENDING
    assert decided_event.attempt_count == 1
    assert not ConsumerReceipt.objects.filter(event=decided_event).exists()

    monkeypatch.undo()
    LocalOutboxPublisher().publish(request_event)
    todo = Todo.objects.get(source_id=current_material.public_id)
    assert todo.status == TodoStatus.OPEN

    LocalOutboxPublisher().publish(decided_event)

    todo.refresh_from_db()
    assert todo.status == TodoStatus.COMPLETED
    assert todo.open_slot is None
    assert Notification.objects.get(todo=todo).status == NotificationStatus.CLOSED


def test_a_stale_decision_event_does_not_settle_a_later_requests_todo(
    django_capture_on_commit_callbacks, requester, confirmer, current_material
) -> None:
    """A returned material is requested again; the old event must not close it."""

    from apps.notifications.models import Todo, TodoStatus
    from apps.platform.outbox.models import OutboxEvent
    from apps.products.consumers import MaterialConfirmationDecidedConsumer

    with django_capture_on_commit_callbacks(execute=True):
        first = submit(requester, current_material, confirmer)
    with django_capture_on_commit_callbacks(execute=True):
        decide(confirmer, first, MaterialConfirmationDecision.RETURNED)
    with django_capture_on_commit_callbacks(execute=True):
        second = submit(requester, current_material, confirmer)

    later_todo = Todo.objects.get(dedup_key=f"material_confirmation:{second.public_id}")
    assert later_todo.status == TodoStatus.OPEN

    stale_event = OutboxEvent.objects.get(
        event_type="material_confirmation.decided",
        aggregate_id=first.public_id,
    )
    MaterialConfirmationDecidedConsumer().consume(stale_event)

    later_todo.refresh_from_db()
    assert later_todo.status == TodoStatus.OPEN
    assert (
        Todo.objects.get(dedup_key=f"material_confirmation:{first.public_id}").status
        == TodoStatus.COMPLETED
    )


@dataclass(frozen=True)
class UndeliveredDecision:
    confirmation: MaterialConfirmation
    todo: Any
    notification: Any
    event: Any


@pytest.fixture
def undelivered_decision(
    django_capture_on_commit_callbacks, requester, confirmer, current_material
) -> UndeliveredDecision:
    """A real decision whose settlement event has not been consumed yet.

    Payload validation can only be exercised from this state. With a still-PENDING
    confirmation the consumer refuses on "carries no decision to settle" first, so
    every field claim would pass untested; and after delivery there is no open todo
    left to prove a rejected event changed nothing.
    """

    from apps.notifications.models import Notification, NotificationStatus, Todo, TodoStatus
    from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent, OutboxStatus

    with django_capture_on_commit_callbacks(execute=True):
        confirmation = submit(requester, current_material, confirmer)
    # Deliberately no capture: the decision commits, its settlement does not run.
    decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    confirmation.refresh_from_db()
    assert confirmation.decision == MaterialConfirmationDecision.APPROVED
    todo = Todo.objects.get(dedup_key=f"material_confirmation:{confirmation.public_id}")
    assert todo.status == TodoStatus.OPEN
    notification = Notification.objects.get(todo=todo)
    assert notification.status == NotificationStatus.UNREAD
    event = OutboxEvent.objects.get(
        event_type="material_confirmation.decided",
        aggregate_id=confirmation.public_id,
    )
    assert event.status == OutboxStatus.PENDING
    assert not ConsumerReceipt.objects.filter(event=event).exists()
    return UndeliveredDecision(
        confirmation=confirmation, todo=todo, notification=notification, event=event
    )


def _retamper(event: Any, changes: dict[str, Any]) -> Any:
    from apps.platform.outbox.models import OutboxEvent

    payload = dict(event.payload_json)
    payload.update(changes)
    OutboxEvent.objects.filter(pk=event.pk).update(payload_json=payload)
    event.refresh_from_db()
    return event


def _assert_settled_nothing(decision: UndeliveredDecision) -> None:
    from apps.notifications.models import NotificationStatus, TodoStatus
    from apps.platform.outbox.models import ConsumerReceipt

    decision.todo.refresh_from_db()
    decision.notification.refresh_from_db()
    assert decision.todo.status == TodoStatus.OPEN
    assert decision.todo.open_slot == 1
    assert decision.notification.status == NotificationStatus.UNREAD
    assert not ConsumerReceipt.objects.filter(event=decision.event).exists()


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param({"actor_user_id": "foreign"}, id="actor-from-another-organization"),
        pytest.param({"actor_user_id": "requester"}, id="actor-is-not-the-confirmer"),
        pytest.param({"material_public_id": str(uuid4())}, id="material-does-not-match"),
        pytest.param({"decision": "RETURNED"}, id="decision-does-not-match"),
        pytest.param({"assignee_id": "requester"}, id="assignee-is-not-the-confirmer"),
        pytest.param(
            {"todo_dedup_key": f"material_confirmation:{uuid4()}"},
            id="dedup-key-names-another-request",
        ),
        pytest.param({"confirmation_public_id": str(uuid4())}, id="confirmation-does-not-resolve"),
        pytest.param({"confirmation_public_id": None}, id="confirmation-id-is-explicitly-null"),
        pytest.param({"material_public_id": None}, id="material-id-is-explicitly-null"),
        pytest.param({"decision": None}, id="decision-is-explicitly-null"),
        pytest.param({"assignee_id": None}, id="assignee-is-explicitly-null"),
        pytest.param({"todo_dedup_key": None}, id="dedup-key-is-explicitly-null"),
    ],
)
def test_a_decision_event_that_contradicts_the_database_settles_nothing(
    undelivered_decision, requester, tamper
) -> None:
    """A malformed or foreign event must not close todos or take a receipt.

    An explicitly null field is a claim of "no value", which a decided confirmation
    never has; only an absent field may fall back to the authoritative row.
    """

    from apps.identity.models.organization import Organization
    from apps.platform.outbox.tasks import LocalOutboxPublisher
    from apps.products.consumers import MaterialConfirmationEventRejected

    actors = {
        "requester": requester.id,
        "foreign": User.objects.create_user(
            organization=Organization.objects.create(name="Foreign Notifier"),
            display_name="Foreign Notifier",
            status=UserStatus.ACTIVE,
            activated_at=timezone.now(),
        ).id,
    }
    changes = {
        key: actors[str(value)] if str(value) in actors else value for key, value in tamper.items()
    }
    event = _retamper(undelivered_decision.event, changes)

    with pytest.raises(MaterialConfirmationEventRejected):
        LocalOutboxPublisher().publish(event)

    _assert_settled_nothing(undelivered_decision)


def test_a_decision_event_filed_under_another_aggregate_settles_nothing(
    undelivered_decision,
) -> None:
    """The stream an event belongs to must be the confirmation it claims to settle."""

    from apps.platform.outbox.models import OutboxEvent
    from apps.platform.outbox.tasks import LocalOutboxPublisher
    from apps.products.consumers import MaterialConfirmationEventRejected

    OutboxEvent.objects.filter(pk=undelivered_decision.event.pk).update(aggregate_id=uuid4())
    undelivered_decision.event.refresh_from_db()

    with pytest.raises(MaterialConfirmationEventRejected):
        LocalOutboxPublisher().publish(undelivered_decision.event)

    _assert_settled_nothing(undelivered_decision)


def test_an_event_missing_a_field_added_later_still_settles_its_todo(
    undelivered_decision,
) -> None:
    """Older events predate payload fields; absence falls back to the database."""

    from apps.notifications.models import NotificationStatus, TodoStatus
    from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent
    from apps.platform.outbox.tasks import LocalOutboxPublisher

    payload = dict(undelivered_decision.event.payload_json)
    for key in ("material_public_id", "decision", "assignee_id", "todo_dedup_key"):
        payload.pop(key)
    OutboxEvent.objects.filter(pk=undelivered_decision.event.pk).update(payload_json=payload)
    undelivered_decision.event.refresh_from_db()

    LocalOutboxPublisher().publish(undelivered_decision.event)

    undelivered_decision.todo.refresh_from_db()
    undelivered_decision.notification.refresh_from_db()
    assert undelivered_decision.todo.status == TodoStatus.COMPLETED
    assert undelivered_decision.notification.status == NotificationStatus.CLOSED
    assert ConsumerReceipt.objects.filter(event=undelivered_decision.event).exists()


def test_a_settlement_is_refused_when_the_confirmer_lost_the_confirm_action(
    undelivered_decision, confirmer
) -> None:
    """The settle command judges the locked todo itself, not the event's word.

    A projection consumer believes whatever an event says, so the right to close a
    todo has to be re-established where the write happens.
    """

    from apps.authorization.models.assignment import RoleAssignment
    from apps.platform.outbox.tasks import LocalOutboxPublisher

    RoleAssignment.objects.filter(
        user=confirmer, role__role_code="ROLE_PRODUCT_MATERIAL_CONFIRM"
    ).delete()

    with pytest.raises(PermissionDeniedError):
        LocalOutboxPublisher().publish(undelivered_decision.event)

    _assert_settled_nothing(undelivered_decision)


def test_the_decision_settlement_event_can_be_replayed_without_reopening(
    django_capture_on_commit_callbacks, requester, confirmer, current_material
) -> None:
    from apps.notifications.models import Todo, TodoStatus
    from apps.platform.outbox.models import OutboxEvent, OutboxStatus
    from apps.products.consumers import MaterialConfirmationDecidedConsumer

    with django_capture_on_commit_callbacks(execute=True):
        confirmation = submit(requester, current_material, confirmer)
    with django_capture_on_commit_callbacks(execute=True):
        decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    event = OutboxEvent.objects.get(
        event_type="material_confirmation.decided",
        aggregate_id=confirmation.public_id,
    )
    assert event.status == OutboxStatus.PUBLISHED

    MaterialConfirmationDecidedConsumer().consume(event)

    todos = Todo.objects.filter(
        source_type="product_material",
        source_id=current_material.public_id,
    )
    assert todos.count() == 1
    assert todos.get().status == TodoStatus.COMPLETED


def test_making_a_material_current_refuses_an_actor_from_another_organization(
    current_material, organization, controlled_document_version, grant_action
) -> None:
    from apps.identity.models.organization import Organization

    outsider = User.objects.create_user(
        organization=Organization.objects.create(name="Foreign Corp"),
        display_name="Outsider",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(outsider, "product_material.manage", "product_material")
    newer = ProductMaterial.objects.create(
        organization=organization,
        change_set=current_material.change_set,
        owner_type=current_material.owner_type,
        owner_id=current_material.owner_id,
        material_type_code=current_material.material_type_code,
        document_version=controlled_document_version(content=b"%PDF-1.4 foreign"),
        version_no=2,
    )

    with pytest.raises(PermissionDeniedError):
        make_material_current(newer, context=CommandContext.for_actor(outsider))

    newer.refresh_from_db()
    current_material.refresh_from_db()
    assert newer.current_slot is None
    assert current_material.current_slot == 1


def test_making_a_material_current_judges_the_stored_sensitivity_not_the_passed_instance(
    requester, current_material, organization, controlled_document_version
) -> None:
    """A caller holding a stale in-memory row must not promote above clearance."""

    from apps.authorization.models.role import (
        DataSensitivityLevel,
        PermissionAction,
        Role,
        RolePermission,
    )

    RolePermission.objects.filter(
        role=Role.objects.get(role_code="ROLE_PRODUCT_MATERIAL_MANAGE"),
        action=PermissionAction.objects.get(action_code="product_material.manage"),
    ).update(max_data_level=DataSensitivityLevel.INTERNAL)
    newer = ProductMaterial.objects.create(
        organization=organization,
        change_set=current_material.change_set,
        owner_type=current_material.owner_type,
        owner_id=current_material.owner_id,
        material_type_code=current_material.material_type_code,
        document_version=controlled_document_version(content=b"%PDF-1.4 secret"),
        version_no=2,
        sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
    )
    newer.sensitivity_level = DataSensitivityLevel.INTERNAL

    with pytest.raises(PermissionDeniedError):
        make_material_current(newer, context=CommandContext.for_actor(requester))

    newer.refresh_from_db()
    assert newer.current_slot is None
    assert newer.sensitivity_level == DataSensitivityLevel.HIGHLY_SENSITIVE


def test_a_decision_is_audited_against_the_file_that_was_reviewed(
    requester, confirmer, current_material
) -> None:
    confirmation = submit(requester, current_material, confirmer)

    decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)

    event = AuditEvent.objects.get(
        action_code="product_material.confirm",
        resource_public_id=confirmation.public_id,
    )
    assert event.after_summary["decision"] == MaterialConfirmationDecision.APPROVED
    assert event.after_summary["content_hash"] == confirmation.content_hash


def test_a_decision_is_refused_when_the_reviewed_bytes_no_longer_match(
    requester, confirmer, current_material
) -> None:
    confirmation = submit(requester, current_material, confirmer)
    MaterialConfirmation.objects.filter(pk=confirmation.pk).update(content_hash="0" * 64)

    with pytest.raises(MaterialConfirmationRejected):
        decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)


def test_a_receipt_from_an_earlier_build_no_longer_strands_an_open_todo(
    django_capture_on_commit_callbacks, undelivered_decision, requester
) -> None:
    """Upgrade path for settlements an older build receipted into thin air.

    That build settled inside the deciding transaction, so the receipt was written
    while the request's own todo did not exist yet. The receipt legitimately stops
    the consumer from running again, which leaves an APPROVED material wearing an
    OPEN todo. The repair keeps the old receipt and appends a new settlement event.
    """

    from apps.notifications.models import NotificationStatus, TodoStatus
    from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent, OutboxStatus
    from apps.platform.outbox.tasks import LocalOutboxPublisher
    from apps.products.services.material_confirmation_repair import (
        REISSUE_REASON,
        ReissueSettlementForDecidedConfirmations,
    )

    stale_event = undelivered_decision.event
    ConsumerReceipt.objects.create(event=stale_event, consumer_code="material_confirmation_decided")
    OutboxEvent.objects.filter(pk=stale_event.pk).update(
        status=OutboxStatus.PUBLISHED, published_at=timezone.now()
    )
    stale_event.refresh_from_db()
    # The receipt is what makes this unrecoverable by replay alone.
    LocalOutboxPublisher().publish(stale_event)
    undelivered_decision.todo.refresh_from_db()
    assert undelivered_decision.todo.status == TodoStatus.OPEN

    with django_capture_on_commit_callbacks(execute=True):
        reissued = ReissueSettlementForDecidedConfirmations(
            context=CommandContext.for_actor(requester),
            confirmation_public_ids=[undelivered_decision.confirmation.public_id],
        ).execute()

    assert reissued == [undelivered_decision.confirmation.public_id]
    undelivered_decision.todo.refresh_from_db()
    undelivered_decision.notification.refresh_from_db()
    assert undelivered_decision.todo.status == TodoStatus.COMPLETED
    assert undelivered_decision.todo.open_slot is None
    assert undelivered_decision.notification.status == NotificationStatus.CLOSED
    # History is kept: the old receipt stays, the repair earns its own.
    assert ConsumerReceipt.objects.filter(event=stale_event).exists()
    repair = OutboxEvent.objects.get(
        event_type="material_confirmation.decided",
        aggregate_id=undelivered_decision.confirmation.public_id,
        payload_json__reissue_reason=REISSUE_REASON,
    )
    assert repair.status == OutboxStatus.PUBLISHED
    assert ConsumerReceipt.objects.filter(event=repair).exists()
    assert AuditEvent.objects.filter(
        action_code="product_material.confirmation_settle_reissue",
        resource_public_id=undelivered_decision.confirmation.public_id,
        actor_user=requester,
    ).exists()
    repairs = MaterialConfirmationSettlementRepair.objects.filter(
        confirmation=undelivered_decision.confirmation
    )
    assert repairs.count() == 1
    assert repairs.get().todo_public_id == undelivered_decision.todo.public_id


def test_the_repair_leaves_an_undelivered_settlement_to_converge_on_its_own(
    undelivered_decision, requester
) -> None:
    """A settlement still in flight needs delivery, not a duplicate event."""

    from apps.platform.outbox.models import OutboxEvent
    from apps.products.services.material_confirmation_repair import (
        ReissueSettlementForDecidedConfirmations,
    )

    reissued = ReissueSettlementForDecidedConfirmations(
        context=CommandContext.for_actor(requester),
        confirmation_public_ids=[undelivered_decision.confirmation.public_id],
    ).execute()

    assert reissued == []
    assert (
        OutboxEvent.objects.filter(
            event_type="material_confirmation.decided",
            aggregate_id=undelivered_decision.confirmation.public_id,
        ).count()
        == 1
    )


def test_the_repair_refuses_an_actor_without_the_manage_action(
    undelivered_decision, confirmer
) -> None:
    from apps.platform.outbox.models import OutboxEvent
    from apps.products.services.material_confirmation_repair import (
        ReissueSettlementForDecidedConfirmations,
    )

    OutboxEvent.objects.filter(pk=undelivered_decision.event.pk).delete()

    with pytest.raises(PermissionDeniedError):
        ReissueSettlementForDecidedConfirmations(
            context=CommandContext.for_actor(confirmer),
            confirmation_public_ids=[undelivered_decision.confirmation.public_id],
        ).execute()

    assert not OutboxEvent.objects.filter(
        event_type="material_confirmation.decided",
        aggregate_id=undelivered_decision.confirmation.public_id,
    ).exists()
    assert not MaterialConfirmationSettlementRepair.objects.exists()


def _strand_settlement(material, requester, confirmer, capture, monkeypatch) -> Any:
    """Reproduce an older build's fact: receipted settlement, still-open todo.

    That build settled inside the deciding transaction, so its consumer closed
    nothing while still earning a receipt. A consumer that does nothing reproduces
    exactly that, without hand-writing the receipt the repair has to work around.
    """

    from apps.notifications.models import Todo, TodoStatus
    from apps.platform.outbox.models import ConsumerReceipt, OutboxEvent, OutboxStatus
    from apps.products.consumers import MaterialConfirmationDecidedConsumer

    with capture(execute=True):
        confirmation = submit(requester, material, confirmer)
    monkeypatch.setattr(
        MaterialConfirmationDecidedConsumer, "consume", lambda self, event: None, raising=True
    )
    with capture(execute=True):
        decide(confirmer, confirmation, MaterialConfirmationDecision.APPROVED)
    monkeypatch.undo()

    event = OutboxEvent.objects.get(
        event_type="material_confirmation.decided",
        aggregate_id=confirmation.public_id,
    )
    assert event.status == OutboxStatus.PUBLISHED
    assert ConsumerReceipt.objects.filter(event=event).exists()
    todo = Todo.objects.get(dedup_key=f"material_confirmation:{confirmation.public_id}")
    assert todo.status == TodoStatus.OPEN
    return confirmation, todo


def test_the_repair_leaves_alone_the_stranded_todo_it_was_not_asked_about(
    django_capture_on_commit_callbacks,
    monkeypatch,
    requester,
    confirmer,
    current_material,
    organization,
    change_set,
    controlled_document_version,
) -> None:
    """A repair moves real business facts, so its scope is the caller's, not a scan.

    Reporting candidates is read-only and may look at everything open; deciding to
    reissue is a named list, so a seed or an operator can answer for exactly what it
    touched instead of dragging along work nobody asked about.
    """

    from apps.notifications.models import TodoStatus
    from apps.products.services.material_confirmation_repair import (
        ReissueSettlementForDecidedConfirmations,
        stranded_settlement_candidates,
    )

    named, named_todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )
    other_material = ProductMaterial.objects.create(
        organization=organization,
        change_set=change_set,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=change_set.product_id,
        material_type_code="PRODUCT_MANUAL",
        document_version=controlled_document_version(content=b"%PDF-1.4 manual"),
        version_no=1,
        current_slot=1,
    )
    unnamed, unnamed_todo = _strand_settlement(
        other_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )

    candidates = stranded_settlement_candidates(organization_id=requester.organization_id)
    assert set(candidates) == {named.public_id, unnamed.public_id}

    with django_capture_on_commit_callbacks(execute=True):
        reissued = ReissueSettlementForDecidedConfirmations(
            context=CommandContext.for_actor(requester),
            confirmation_public_ids=[named.public_id],
        ).execute()

    named_todo.refresh_from_db()
    unnamed_todo.refresh_from_db()
    assert reissued == [named.public_id]
    assert named_todo.status == TodoStatus.COMPLETED
    assert unnamed_todo.status == TodoStatus.OPEN
    assert not MaterialConfirmationSettlementRepair.objects.filter(confirmation=unnamed).exists()


def test_a_stranded_todo_is_repaired_once_even_if_the_repair_settled_nothing(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """One repair per stranded todo, decided by the database and not by a re-scan.

    If the reissued settlement itself closes nothing, the todo stays OPEN and visible
    to an operator. Repairing again on every pass would append events and audit
    records forever while changing nothing.
    """

    from apps.notifications.models import TodoStatus
    from apps.platform.outbox.models import OutboxEvent
    from apps.products.consumers import MaterialConfirmationDecidedConsumer
    from apps.products.services.material_confirmation_repair import (
        REISSUE_REASON,
        ReissueSettlementForDecidedConfirmations,
    )

    confirmation, todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )

    def _repair() -> list:
        return ReissueSettlementForDecidedConfirmations(
            context=CommandContext.for_actor(requester),
            confirmation_public_ids=[confirmation.public_id],
        ).execute()

    monkeypatch.setattr(
        MaterialConfirmationDecidedConsumer, "consume", lambda self, event: None, raising=True
    )
    with django_capture_on_commit_callbacks(execute=True):
        first = _repair()
    monkeypatch.undo()
    todo.refresh_from_db()
    assert first == [confirmation.public_id]
    assert todo.status == TodoStatus.OPEN

    second = _repair()

    assert second == []
    assert (
        MaterialConfirmationSettlementRepair.objects.filter(confirmation=confirmation).count() == 1
    )
    assert (
        OutboxEvent.objects.filter(
            event_type="material_confirmation.decided",
            aggregate_id=confirmation.public_id,
            payload_json__reissue_reason=REISSUE_REASON,
        ).count()
        == 1
    )
    assert (
        AuditEvent.objects.filter(
            action_code="product_material.confirmation_settle_reissue",
            resource_public_id=confirmation.public_id,
        ).count()
        == 1
    )


def test_a_database_failure_during_a_repair_is_not_read_as_a_duplicate(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """Only the repair key's own duplicate means "already repaired".

    Any other integrity failure - an outbox row, an audit row, a constraint added
    later - is a real failure. Reporting it as an idempotent skip would hide a broken
    repair behind a clean exit code.
    """

    from django.db import IntegrityError

    from apps.notifications.models import TodoStatus
    from apps.platform.outbox.models import OutboxEvent
    from apps.products.services import material_confirmation_repair as repair_module
    from apps.products.services.material_confirmation_repair import (
        ReissueSettlementForDecidedConfirmations,
    )

    confirmation, todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise IntegrityError(1452, "Cannot add or update a child row: audit_event")

    monkeypatch.setattr(repair_module, "append_event", _boom)

    with pytest.raises(IntegrityError):
        ReissueSettlementForDecidedConfirmations(
            context=CommandContext.for_actor(requester),
            confirmation_public_ids=[confirmation.public_id],
        ).execute()

    todo.refresh_from_db()
    assert todo.status == TodoStatus.OPEN
    assert not MaterialConfirmationSettlementRepair.objects.exists()
    assert (
        OutboxEvent.objects.filter(
            event_type="material_confirmation.decided",
            aggregate_id=confirmation.public_id,
        ).count()
        == 1
    )


def test_a_non_duplicate_error_that_names_the_repair_key_is_not_an_idempotent_skip() -> None:
    """Naming the constraint is not enough; only MySQL 1062 on that key is a skip."""

    from django.db import IntegrityError

    from apps.products.services.material_confirmation_repair import (
        REPAIR_UNIQUE_CONSTRAINT,
        _is_duplicate_repair,
    )

    quoted = IntegrityError(
        1452,
        f"Cannot add or update a child row: a foreign key constraint fails "
        f"(`db`.`t`, CONSTRAINT `{REPAIR_UNIQUE_CONSTRAINT}`)",
    )
    assert not _is_duplicate_repair(quoted)

    duplicate = IntegrityError(
        1062,
        f"Duplicate entry '1-uuid' for key '{REPAIR_UNIQUE_CONSTRAINT}'",
    )
    assert _is_duplicate_repair(duplicate)

    # Django sometimes wraps the driver error; the errno lives on the cause.
    wrapped = IntegrityError(f"Duplicate entry for key '{REPAIR_UNIQUE_CONSTRAINT}'")
    wrapped.__cause__ = IntegrityError(
        1062, f"Duplicate entry '1-uuid' for key '{REPAIR_UNIQUE_CONSTRAINT}'"
    )
    assert _is_duplicate_repair(wrapped)


def test_a_non_1062_error_that_names_the_repair_key_propagates_through_repair(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """A quoted constraint name without errno 1062 must not become 'already repaired'."""

    from django.db import IntegrityError

    from apps.notifications.models import TodoStatus
    from apps.products.services.material_confirmation_repair import (
        REPAIR_UNIQUE_CONSTRAINT,
        ReissueSettlementForDecidedConfirmations,
    )

    confirmation, todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise IntegrityError(
            1452,
            f"Cannot add or update a child row: a foreign key constraint fails "
            f"(`db`.`t`, CONSTRAINT `{REPAIR_UNIQUE_CONSTRAINT}`)",
        )

    monkeypatch.setattr(MaterialConfirmationSettlementRepair.objects, "create", _boom)

    with pytest.raises(IntegrityError) as raised:
        ReissueSettlementForDecidedConfirmations(
            context=CommandContext.for_actor(requester),
            confirmation_public_ids=[confirmation.public_id],
        ).execute()

    assert raised.value.args[0] == 1452
    todo.refresh_from_db()
    assert todo.status == TodoStatus.OPEN
    assert not MaterialConfirmationSettlementRepair.objects.exists()


def test_a_scoped_candidate_query_never_reads_open_todos_outside_the_named_confirmations(
    django_capture_on_commit_callbacks,
    monkeypatch,
    requester,
    confirmer,
    current_material,
    organization,
    change_set,
    controlled_document_version,
) -> None:
    """Object-level scope is a SQL filter, not a Python filter after a broad read.

    A seed naming its own fixtures must not pull every open confirmation todo in the
    organization into memory first. The query itself is limited to those dedup keys.
    """

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.products.services.material_confirmation_repair import (
        stranded_settlement_candidates,
    )

    named, _named_todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )
    other_material = ProductMaterial.objects.create(
        organization=organization,
        change_set=change_set,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=change_set.product_id,
        material_type_code="PRODUCT_MANUAL",
        document_version=controlled_document_version(content=b"%PDF-1.4 manual"),
        version_no=1,
        current_slot=1,
    )
    unnamed, _unnamed_todo = _strand_settlement(
        other_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )

    with CaptureQueriesContext(connection) as captured:
        candidates = stranded_settlement_candidates(
            organization_id=requester.organization_id,
            confirmation_public_ids=[named.public_id],
        )

    assert candidates == [named.public_id]
    assert unnamed.public_id not in candidates
    todo_sql = " ".join(
        query["sql"] for query in captured.captured_queries if "notifications_todo" in query["sql"]
    ).upper()
    # Object scope is `dedup_key__in`, never the org-wide `dedup_key__startswith` LIKE.
    assert "NOTIFICATIONS_TODO" in todo_sql
    assert " IN " in todo_sql
    assert " LIKE " not in todo_sql


@pytest.mark.django_db(transaction=True)
def test_a_repair_and_a_settlement_do_not_deadlock_on_the_same_material(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """Production settle must reach the material lock without already holding the todo.

    Sync sits on the real production boundary: after repair holds confirmation/material,
    and inside production `SettleOneOpenTodo._locked_source` immediately before its
    `select_for_update` on the material. At that instant repair probes the todo with
    `NOWAIT`. If settle had regressed to todo-then-material, the todo is already held
    and the probe fails this test deterministically. A hand-written reverse `execute`
    stub is not used - only production settle runs, so changing production lock order
    is what turns this gate red.
    """

    import threading

    from apps.notifications.models import TodoStatus
    from apps.notifications.services.todos import SettleOneOpenTodo
    from apps.products.services.material_confirmation_repair import (
        ReissueSettlementForDecidedConfirmations,
    )

    confirmation, todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )
    dedup_key = f"material_confirmation:{confirmation.public_id}"
    repair_holds_material = threading.Event()
    settle_at_material_lock = threading.Event()
    release_settle_into_material_lock = threading.Event()

    original_require = ReissueSettlementForDecidedConfirmations._require_may_repair
    original_locked_source = SettleOneOpenTodo._locked_source

    def _repair_checks_settle_has_not_locked_todo(self: Any, locked: Any) -> None:
        original_require(self, locked)
        repair_holds_material.set()
        assert settle_at_material_lock.wait(timeout=10), (
            "settle never reached production material lock"
        )
        _assert_todo_row_is_free(
            organization_id=requester.organization_id,
            dedup_key=dedup_key,
        )
        release_settle_into_material_lock.set()

    def _settle_pauses_before_production_material_lock(self: Any, **kwargs: Any) -> Any:
        settle_at_material_lock.set()
        assert release_settle_into_material_lock.wait(timeout=10), (
            "repair never released settle into the material lock"
        )
        return original_locked_source(self, **kwargs)

    monkeypatch.setattr(
        ReissueSettlementForDecidedConfirmations,
        "_require_may_repair",
        _repair_checks_settle_has_not_locked_todo,
    )
    monkeypatch.setattr(
        SettleOneOpenTodo,
        "_locked_source",
        _settle_pauses_before_production_material_lock,
    )

    def _repair() -> None:
        ReissueSettlementForDecidedConfirmations(
            context=CommandContext.for_actor(requester),
            confirmation_public_ids=[confirmation.public_id],
        ).execute()

    def _settle() -> None:
        assert repair_holds_material.wait(timeout=10), "repair never held the material"
        SettleOneOpenTodo(
            context=CommandContext.for_actor(confirmer),
            assignee_id=confirmer.id,
            dedup_key=dedup_key,
            status=TodoStatus.COMPLETED,
            close_reason="SOURCE_COMPLETED",
        ).execute()

    results = _run_repair_against_settlement(repair=_repair, settle=_settle)

    assert results == ["done:repair", "done:settle"] or results == ["done:settle", "done:repair"], (
        results
    )
    todo.refresh_from_db()
    assert todo.status == TodoStatus.COMPLETED
    assert todo.open_slot is None


def _assert_todo_row_is_free(*, organization_id: int, dedup_key: str) -> None:
    """Fail if another connection already holds the todo, i.e. locked it before material."""

    from django.db import DatabaseError, transaction

    from apps.notifications.models import Todo

    try:
        with transaction.atomic():
            # NOWAIT: if settle already locked the ask, MySQL rejects immediately (3572).
            Todo.objects.select_for_update(nowait=True).filter(
                organization_id=organization_id,
                dedup_key=dedup_key,
            ).order_by("pk").first()
    except DatabaseError as exc:
        if _is_mysql_nowait_rejection(exc):
            raise AssertionError(
                "Settle held the todo before locking the material; "
                "SettleOneOpenTodo lock order has regressed to todo-then-material."
            ) from exc
        raise


def _is_mysql_nowait_rejection(error: BaseException) -> bool:
    current: BaseException | None = error
    while current is not None:
        text = str(current).upper()
        if "3572" in text or "NOWAIT" in text:
            return True
        args = getattr(current, "args", ())
        if args and args[0] == 3572:
            return True
        current = current.__cause__ or current.__context__
    return False


def _run_repair_against_settlement(*, repair: Any, settle: Any) -> list[str]:
    import threading

    from django.db import connection

    results: list[str] = []
    lock = threading.Lock()

    def _run(label: str, work: Any) -> None:
        connection.close()
        try:
            work()
            with lock:
                results.append(f"done:{label}")
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            with lock:
                results.append(f"error:{type(exc).__name__}:{label}:{exc}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_run, args=("repair", repair)),
        threading.Thread(target=_run, args=("settle", settle)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "repair and settlement did not finish"
    return results


@pytest.mark.django_db(transaction=True)
def test_two_repair_processes_produce_one_reissued_settlement(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """Compensation is a fact, so the database decides whether it already exists.

    Two operators, or an operator and a retry, can reach the same stranded todo at
    once. "Check, then insert" would let both append a settlement event and an audit
    record for one repair, so the unique repair key is the arbiter and the loser
    writes nothing at all.
    """

    import threading

    from django.db import connection

    from apps.notifications.models import TodoStatus
    from apps.platform.outbox.models import OutboxEvent
    from apps.products.services.material_confirmation_repair import (
        REISSUE_REASON,
        ReissueSettlementForDecidedConfirmations,
    )

    confirmation, todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )

    results: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def _repair(label: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=10)
            reissued = ReissueSettlementForDecidedConfirmations(
                context=CommandContext.for_actor(requester),
                confirmation_public_ids=[confirmation.public_id],
            ).execute()
            with lock:
                results.append(f"reissued:{label}" if reissued else f"skipped:{label}")
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            with lock:
                results.append(f"error:{type(exc).__name__}:{label}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_repair, args=("a",)),
        threading.Thread(target=_repair, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "concurrent settlement repair did not finish"

    assert not [item for item in results if item.startswith("error:")], results
    assert len([item for item in results if item.startswith("reissued:")]) == 1, results
    assert len([item for item in results if item.startswith("skipped:")]) == 1, results
    assert (
        MaterialConfirmationSettlementRepair.objects.filter(confirmation=confirmation).count() == 1
    )
    assert (
        OutboxEvent.objects.filter(
            event_type="material_confirmation.decided",
            aggregate_id=confirmation.public_id,
            payload_json__reissue_reason=REISSUE_REASON,
        ).count()
        == 1
    )
    assert (
        AuditEvent.objects.filter(
            action_code="product_material.confirmation_settle_reissue",
            resource_public_id=confirmation.public_id,
        ).count()
        == 1
    )
    todo.refresh_from_db()
    assert todo.status == TodoStatus.COMPLETED
    assert todo.open_slot is None


def test_the_operations_command_reports_before_it_moves_anything(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """History repair is an operator's decision, taken twice: report, then apply.

    Nothing in request handling or seeding may sweep an organization's history, so
    the sweep lives behind a command that says what it found and only closes todos
    when asked to.
    """

    from django.core.management import call_command

    from apps.notifications.models import TodoStatus

    confirmation, todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )

    call_command(
        "repair_material_confirmation_settlements",
        "--actor-login-key",
        requester.login_key,
    )

    todo.refresh_from_db()
    assert todo.status == TodoStatus.OPEN
    assert not MaterialConfirmationSettlementRepair.objects.exists()

    call_command(
        "repair_material_confirmation_settlements",
        "--actor-login-key",
        requester.login_key,
        "--apply",
    )

    todo.refresh_from_db()
    assert todo.status == TodoStatus.COMPLETED
    assert (
        MaterialConfirmationSettlementRepair.objects.filter(confirmation=confirmation).count() == 1
    )


def test_the_operations_command_fails_when_a_todo_it_repaired_is_still_open(
    django_capture_on_commit_callbacks, monkeypatch, requester, confirmer, current_material
) -> None:
    """An operator learns the repair did not close the ask, from the exit code.

    A repair that reissued nothing because the sentinel already exists, or whose
    settlement never landed, leaves the todo exactly as open as before. Counting
    reissues would call that a success and hide the one fact that matters.
    """

    from django.core.management import call_command
    from django.core.management.base import CommandError

    from apps.notifications.models import TodoStatus
    from apps.products.consumers import MaterialConfirmationDecidedConsumer

    confirmation, todo = _strand_settlement(
        current_material, requester, confirmer, django_capture_on_commit_callbacks, monkeypatch
    )
    monkeypatch.setattr(
        MaterialConfirmationDecidedConsumer, "consume", lambda self, event: None, raising=True
    )

    with pytest.raises(CommandError, match="still has an open confirmation todo"):
        call_command(
            "repair_material_confirmation_settlements",
            "--actor-login-key",
            requester.login_key,
            "--apply",
        )

    todo.refresh_from_db()
    assert todo.status == TodoStatus.OPEN
    assert (
        MaterialConfirmationSettlementRepair.objects.filter(confirmation=confirmation).count() == 1
    )


def test_a_settlement_is_refused_when_the_material_outranks_the_confirmers_clearance(
    undelivered_decision, confirmer, current_material
) -> None:
    """The settle judges the locked material's own level, whatever the caller read.

    Whoever asks for a settlement read the material outside the settling transaction,
    so its sensitivity may have been raised since. A stale lower level must not buy
    the right to close a todo on a material the actor may no longer touch.
    """

    from apps.authorization.models.role import (
        DataSensitivityLevel,
        PermissionAction,
        Role,
        RolePermission,
    )
    from apps.platform.outbox.tasks import LocalOutboxPublisher

    RolePermission.objects.filter(
        role=Role.objects.get(role_code="ROLE_PRODUCT_MATERIAL_CONFIRM"),
        action=PermissionAction.objects.get(action_code="product_material.confirm"),
    ).update(max_data_level=DataSensitivityLevel.INTERNAL)
    ProductMaterial.objects.filter(pk=current_material.pk).update(
        sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE
    )

    with pytest.raises(PermissionDeniedError):
        LocalOutboxPublisher().publish(undelivered_decision.event)

    _assert_settled_nothing(undelivered_decision)


def test_confirmation_survives_when_local_outbox_dispatch_fails(
    monkeypatch, django_capture_on_commit_callbacks, requester, confirmer, current_material
) -> None:
    """Notification/todo projection failure must not unwind the confirmation."""

    from apps.platform.outbox.models import OutboxEvent, OutboxStatus
    from apps.platform.outbox.tasks import LocalOutboxPublisher

    def _boom(self: Any, event: Any) -> None:
        raise RuntimeError("projection unavailable")

    monkeypatch.setattr(LocalOutboxPublisher, "publish", _boom)

    with django_capture_on_commit_callbacks(execute=True):
        confirmation = submit(requester, current_material, confirmer)

    assert MaterialConfirmation.objects.filter(pk=confirmation.pk).exists()
    pending = OutboxEvent.objects.get(aggregate_id=confirmation.public_id)
    assert pending.status == OutboxStatus.PENDING
    assert pending.attempt_count == 1
    assert pending.last_error_code == "LOCAL_DISPATCH_FAILED"
    assert pending.next_attempt_at is not None
