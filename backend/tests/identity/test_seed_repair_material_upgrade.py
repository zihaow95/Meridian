"""Repair seed must upgrade forged labels without overwriting material history."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

import pytest
from django.conf import settings
from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentSource,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    VersionStatus,
)
from apps.identity.management.commands.seed_e2e_user import Command as SeedE2ECommand
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.products.models import (
    AttributeOwnerType,
    MaterialConfirmation,
    MaterialConfirmationDecision,
    MaterialStatus,
    ProductAsset,
    ProductLifecycleStatus,
    ProductMaterial,
    ProductSourceType,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def published_todo_notification_catalog(organization: Organization, active_user: User) -> None:
    """`todo.requested` projection needs a live template + delivery policy."""

    from apps.configuration.models import (
        ConfigurationDefinition,
        ConfigurationStatus,
        ConfigurationVersion,
    )
    from apps.configuration.schema_registry import (
        NOTIFICATION_DELIVERY_POLICY_CODE,
        NOTIFICATION_TEMPLATE_CATALOG_CODE,
    )

    contents = (
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
    )
    for code, content in contents:
        definition, _ = ConfigurationDefinition.objects.get_or_create(
            organization=organization,
            definition_code=code,
            defaults={"name": code, "description": ""},
        )
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
def yogurt_product(organization: Organization, active_user: User) -> ProductAsset:
    return ProductAsset.objects.create(
        organization=organization,
        business_no="E2E-REPAIR-LABEL",
        name="Repair Label Product",
        category_code="YOGURT",
        source_type=ProductSourceType.LEGACY_IMPORT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )


def _forged_document(
    *,
    organization: Organization,
    actor: User,
    marker: str,
) -> DocumentVersion:
    storage_root = settings.FILE_STORAGE_ROOT
    storage_root.mkdir(parents=True, exist_ok=True)
    payload = f"forged-{marker}".encode()
    digest = hashlib.sha256(payload).hexdigest()
    document = Document.objects.create(
        organization_id=organization.id,
        document_code=f"FORGED-{marker}",
        title=f"Forged {marker}",
        source=DocumentSource.PRODUCT,
    )
    object_key = f"e2e/forged/{marker}.bin"
    file_object = FileObject.objects.create(
        organization_id=organization.id,
        object_key=object_key,
        storage_backend=StorageBackend.NAS_NFS,
        size_bytes=len(payload),
        sha256=digest,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.ACTIVE,
    )
    (storage_root / object_key).parent.mkdir(parents=True, exist_ok=True)
    (storage_root / object_key).write_bytes(payload)
    return DocumentVersion.objects.create(
        organization_id=organization.id,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename=f"{marker}.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.CONTROLLED,
        catalog_item_code="PRODUCT_LABEL",
        uploaded_by=actor,
        uploaded_at=timezone.now(),
    )


def test_repair_seed_upgrades_forged_live_approval_without_overwriting_history(
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")
    forged_version = _forged_document(
        organization=yogurt_product.organization,
        actor=active_user,
        marker="live",
    )
    old = ProductMaterial.objects.create(
        organization_id=yogurt_product.organization_id,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        version_no=1,
        document_version=forged_version,
        material_status=MaterialStatus.APPROVED,
        current_slot=1,
        sensitivity_level=forged_version.sensitivity_level,
    )
    MaterialConfirmation.objects.create(
        organization_id=yogurt_product.organization_id,
        material=old,
        document_version=forged_version,
        content_hash="0" * 64,
        requested_by=active_user,
        requested_at=timezone.now(),
        confirmer=active_user,
        decision=MaterialConfirmationDecision.APPROVED,
        decided_at=timezone.now(),
        live_slot=1,
    )

    SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    old.refresh_from_db()
    assert old.document_version_id == forged_version.id
    assert old.current_slot is None
    assert old.material_status == MaterialStatus.INACTIVE
    assert not MaterialConfirmation.objects.filter(material=old, live_slot=1).exists()

    current = ProductMaterial.objects.get(
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        current_slot=1,
    )
    assert current.pk != old.pk
    assert current.version_no == 2
    assert current.document_version_id != forged_version.id
    assert SeedE2ECommand()._has_valid_approved_confirmation(current)


def test_repair_seed_leaves_no_open_confirmation_todo_after_commit_callbacks(
    django_capture_on_commit_callbacks,
    published_todo_notification_catalog: None,
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    """An approved material must never keep a "please confirm" todo open.

    The seed requests and decides in one transaction, so the todo is projected
    only after commit; the settlement has to land after that projection.
    """

    from apps.notifications.models import Notification, NotificationStatus, Todo, TodoStatus

    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")

    with django_capture_on_commit_callbacks(execute=True):
        SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    current = ProductMaterial.objects.get(
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        current_slot=1,
    )
    assert current.material_status == MaterialStatus.APPROVED
    todo = Todo.objects.get(source_type="product_material", source_id=current.public_id)
    assert todo.status == TodoStatus.COMPLETED
    assert todo.open_slot is None
    assert Notification.objects.get(todo=todo).status == NotificationStatus.CLOSED


def test_phase6_seed_converges_its_own_fixture_and_leaves_history_alone(
    django_capture_on_commit_callbacks,
    published_todo_notification_catalog: None,
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    """The acceptance seed answers for the fixtures it created, not for history.

    An organization that has run for months holds confirmations from builds and runs
    this seed never saw. Repairing those would move business facts nobody asked about,
    so scope is the confirmations `seed_e2e_user` recorded on this run - and a stranded
    todo outside that scope is left for the operations command.
    """

    from apps.identity.management.commands.seed_e2e_user import (
        fixture_material_confirmation_ids,
    )
    from apps.identity.management.commands.seed_phase6_acceptance import (
        Command as SeedPhase6Command,
    )
    from apps.notifications.models import Todo, TodoStatus
    from apps.products.models import MaterialConfirmationSettlementRepair

    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")

    with django_capture_on_commit_callbacks(execute=True):
        SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    current = ProductMaterial.objects.get(
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        current_slot=1,
    )
    confirmation = MaterialConfirmation.objects.get(material=current, live_slot=1)
    assert confirmation.public_id in fixture_material_confirmation_ids()

    todo = Todo.objects.get(source_type="product_material", source_id=current.public_id)
    # Stand the ask back open, the way a run interrupted before its settlement would.
    Todo.objects.filter(pk=todo.pk).update(status=TodoStatus.OPEN, open_slot=1)

    seed = SeedPhase6Command()
    seed._fixture_confirmation_ids = ()
    seed._converge_projection_events(active_user)

    todo.refresh_from_db()
    assert todo.status == TodoStatus.OPEN
    assert not MaterialConfirmationSettlementRepair.objects.exists()

    seed._fixture_confirmation_ids = (confirmation.public_id,)
    seed._converge_projection_events(active_user)

    todo.refresh_from_db()
    assert todo.status == TodoStatus.COMPLETED
    assert MaterialConfirmationSettlementRepair.objects.count() == 1


def test_repair_seed_upgrades_stale_pending_confirmation_on_rerun(
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")
    forged_version = _forged_document(
        organization=yogurt_product.organization,
        actor=active_user,
        marker="pending",
    )
    old = ProductMaterial.objects.create(
        organization_id=yogurt_product.organization_id,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        version_no=1,
        document_version=forged_version,
        material_status=MaterialStatus.DRAFT,
        current_slot=1,
        sensitivity_level=forged_version.sensitivity_level,
    )
    stale_pending = MaterialConfirmation.objects.create(
        organization_id=yogurt_product.organization_id,
        material=old,
        document_version=forged_version,
        content_hash=forged_version.file_object.sha256,
        requested_by=active_user,
        requested_at=timezone.now(),
        confirmer=active_user,
        decision=MaterialConfirmationDecision.PENDING,
    )

    SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    stale_pending.refresh_from_db()
    assert stale_pending.superseded_at is not None
    old.refresh_from_db()
    assert old.document_version_id == forged_version.id
    assert old.current_slot is None

    current = ProductMaterial.objects.get(
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        current_slot=1,
    )
    assert current.pk != old.pk
    assert SeedE2ECommand()._has_valid_approved_confirmation(current)


def test_repair_seed_submit_failure_rolls_back_and_rerun_upgrades_once(
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")
    forged_version = _forged_document(
        organization=yogurt_product.organization,
        actor=active_user,
        marker="submit-fail",
    )
    old = ProductMaterial.objects.create(
        organization_id=yogurt_product.organization_id,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        version_no=1,
        document_version=forged_version,
        material_status=MaterialStatus.APPROVED,
        current_slot=1,
        sensitivity_level=forged_version.sensitivity_level,
    )
    MaterialConfirmation.objects.create(
        organization_id=yogurt_product.organization_id,
        material=old,
        document_version=forged_version,
        content_hash="0" * 64,
        requested_by=active_user,
        requested_at=timezone.now(),
        confirmer=active_user,
        decision=MaterialConfirmationDecision.APPROVED,
        decided_at=timezone.now(),
        live_slot=1,
    )

    from apps.products.services import material_confirmations as confirmations

    real_submit = confirmations.SubmitMaterialConfirmation.execute

    def boom(self):  # noqa: ANN001
        raise RuntimeError("injected submit failure")

    monkeypatch.setattr(confirmations.SubmitMaterialConfirmation, "execute", boom)
    with pytest.raises(RuntimeError, match="injected submit failure"):
        SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    old.refresh_from_db()
    assert old.current_slot == 1
    assert (
        ProductMaterial.objects.filter(
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=yogurt_product.id,
            material_type_code="PRODUCT_LABEL",
        ).count()
        == 1
    )

    monkeypatch.setattr(confirmations.SubmitMaterialConfirmation, "execute", real_submit)
    SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)
    SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    materials = list(
        ProductMaterial.objects.filter(
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=yogurt_product.id,
            material_type_code="PRODUCT_LABEL",
        ).order_by("version_no")
    )
    assert len(materials) == 2
    assert materials[0].pk == old.pk
    assert materials[0].current_slot is None
    assert materials[1].current_slot == 1
    assert materials[1].version_no == 2
    assert SeedE2ECommand()._has_valid_approved_confirmation(materials[1])


def test_repair_seed_decide_failure_rolls_back_and_rerun_upgrades_once(
    yogurt_product: ProductAsset,
    active_user: User,
    grant_action: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grant_action(active_user, "product_material.manage", "product_material")
    grant_action(active_user, "product_material.confirm", "product_material")
    forged_version = _forged_document(
        organization=yogurt_product.organization,
        actor=active_user,
        marker="decide-fail",
    )
    old = ProductMaterial.objects.create(
        organization_id=yogurt_product.organization_id,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=yogurt_product.id,
        material_type_code="PRODUCT_LABEL",
        version_no=1,
        document_version=forged_version,
        material_status=MaterialStatus.APPROVED,
        current_slot=1,
        sensitivity_level=forged_version.sensitivity_level,
    )
    MaterialConfirmation.objects.create(
        organization_id=yogurt_product.organization_id,
        material=old,
        document_version=forged_version,
        content_hash="0" * 64,
        requested_by=active_user,
        requested_at=timezone.now(),
        confirmer=active_user,
        decision=MaterialConfirmationDecision.APPROVED,
        decided_at=timezone.now(),
        live_slot=1,
    )

    from apps.products.services import material_confirmations as confirmations

    real_decide = confirmations.DecideMaterialConfirmation.execute

    def boom(self):  # noqa: ANN001
        raise RuntimeError("injected decide failure")

    monkeypatch.setattr(confirmations.DecideMaterialConfirmation, "execute", boom)
    with pytest.raises(RuntimeError, match="injected decide failure"):
        SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    old.refresh_from_db()
    assert old.current_slot == 1
    assert MaterialConfirmation.objects.filter(material=old, live_slot=1).exists()
    assert (
        ProductMaterial.objects.filter(
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=yogurt_product.id,
            material_type_code="PRODUCT_LABEL",
        ).count()
        == 1
    )

    monkeypatch.setattr(confirmations.DecideMaterialConfirmation, "execute", real_decide)
    SeedE2ECommand()._ensure_approved_product_label(product=yogurt_product, actor=active_user)

    materials = list(
        ProductMaterial.objects.filter(
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=yogurt_product.id,
            material_type_code="PRODUCT_LABEL",
        ).order_by("version_no")
    )
    assert len(materials) == 2
    assert materials[1].version_no == 2
    assert SeedE2ECommand()._has_valid_approved_confirmation(materials[1])
