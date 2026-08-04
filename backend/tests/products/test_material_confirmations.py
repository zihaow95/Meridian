"""Material confirmations are their own record, and only one may be live.

Professional confirmation used to have nowhere to live: `ProductMaterial`
carried a nullable FK to `AttributeConfirmation`, which records a decision about
an attribute group's content hash, not about a file. A row there could never
prove that anybody looked at the bytes, so it cannot be replayed as an approval.
"""

from __future__ import annotations

import importlib
from typing import Any

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
