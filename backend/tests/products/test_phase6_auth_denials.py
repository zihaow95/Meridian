"""Permission denial paths for phase-6 material and legacy writers."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.authorization.models.role import (
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
)
from apps.documents.models import DocumentSource, DocumentVersion
from apps.documents.services.ingest import activate_staged_content, stage_controlled_content
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import AttributeOwnerType, ProductAsset, ProductMaterial
from apps.products.services.create_legacy_baseline import CreateLegacyBaselineDraft
from apps.products.services.legacy_material_intake import CreateLegacyMaterialSubmission

pytestmark = pytest.mark.django_db


@pytest.fixture
def controlled_version(
    organization: Organization, active_user: User
) -> Callable[..., DocumentVersion]:
    storage = get_file_storage()

    def _create(*, sensitivity: str = "HIGHLY_SENSITIVE") -> DocumentVersion:
        content = b"%PDF-1.4 denial"
        temp_path = storage.temp_dir() / f"{uuid4()}.part"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content)
        _, staged = stage_controlled_content(
            organization=organization,
            source_temp_path=Path(temp_path),
            sha256=sha256(content).hexdigest(),
            size_bytes=len(content),
            original_filename="secret.pdf",
            mime_type="application/pdf",
            uploaded_by=active_user,
            source=DocumentSource.MIGRATION,
            catalog_item_code="PRODUCT_LABEL",
            sensitivity_level=sensitivity,
        )
        version = activate_staged_content(staged, storage)
        DocumentVersion.objects.filter(pk=version.pk).update(sensitivity_level=sensitivity)
        version.refresh_from_db()
        return version

    return _create


def test_legacy_intake_refuses_actor_without_create_action(
    active_user: User, controlled_version
) -> None:
    with pytest.raises(PermissionDeniedError):
        CreateLegacyMaterialSubmission(
            context=CommandContext.for_actor(active_user),
            document_version_public_id=controlled_version().public_id,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=1,
            idempotency_key="deny-intake",
        ).execute()


def test_legacy_baseline_draft_refuses_actor_without_draft_create(
    active_user: User,
) -> None:
    with pytest.raises(PermissionDeniedError):
        CreateLegacyBaselineDraft(
            context=CommandContext.for_actor(active_user),
            payload={"name": "Denied", "category_code": "YOGURT"},
            idempotency_key="deny-draft",
        ).execute()


def test_import_batch_draft_accepts_migration_confirm_without_draft_create(
    active_user: User,
    organization: Organization,
    grant_action: Callable[..., None],
) -> None:
    """Phase-3 import confirmation only holds migration.confirm — keep that path."""

    from apps.products.models import ImportBatch, ImportBatchStatus, ImportItem, ImportItemStatus

    grant_action(active_user, "migration.confirm", "migration")
    batch = ImportBatch.objects.create(
        organization=organization,
        template_version="v1",
        status=ImportBatchStatus.PARSED,
        created_by=active_user,
        total_count=1,
    )
    from apps.audit.models import AuditEvent
    from apps.platform.outbox.models import OutboxEvent
    from apps.products.models import ImportItemDecision

    item = ImportItem.objects.create(
        organization=organization,
        batch=batch,
        row_number=1,
        raw_row_digest="a" * 64,
        normalized_payload={"name": "Imported", "category_code": "YOGURT"},
        item_status=ImportItemStatus.VALID,
        decision=ImportItemDecision.CREATE,
    )
    draft = CreateLegacyBaselineDraft(
        context=CommandContext.for_actor(active_user),
        payload={"name": "Imported", "category_code": "YOGURT"},
        idempotency_key="import-draft-ok",
        migration_batch_id=batch.id,
        import_row_number=1,
        business_no_fallback="IMP-001",
    ).execute()
    assert draft.change_set.migration_batch_id == batch.id
    item.refresh_from_db()
    assert item.decision == ImportItemDecision.CREATE
    assert AuditEvent.objects.filter(
        action_code="legacy_baseline.draft.create",
        resource_public_id=draft.change_set.public_id,
    ).exists()
    assert OutboxEvent.objects.filter(
        event_type="legacy_baseline.draft.created",
        aggregate_id=draft.change_set.public_id,
    ).exists()


def test_import_batch_draft_refuses_foreign_batch_id(
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "migration.confirm", "migration")
    with pytest.raises(PermissionDeniedError):
        CreateLegacyBaselineDraft(
            context=CommandContext.for_actor(active_user),
            payload={"name": "Imported", "category_code": "YOGURT"},
            idempotency_key="import-foreign-batch",
            migration_batch_id=9_999_999,
            import_row_number=1,
            business_no_fallback="IMP-X",
        ).execute()


def test_import_batch_draft_requires_row_number(
    active_user: User,
    organization: Organization,
    grant_action: Callable[..., None],
) -> None:
    from apps.platform.api.errors import ValidationFailedError
    from apps.products.models import ImportBatch, ImportBatchStatus, ImportItem, ImportItemStatus

    grant_action(active_user, "migration.confirm", "migration")
    batch = ImportBatch.objects.create(
        organization=organization,
        template_version="v1",
        status=ImportBatchStatus.PARSED,
        created_by=active_user,
        total_count=1,
    )
    ImportItem.objects.create(
        organization=organization,
        batch=batch,
        row_number=1,
        raw_row_digest="b" * 64,
        normalized_payload={"name": "Imported", "category_code": "YOGURT"},
        item_status=ImportItemStatus.VALID,
    )
    with pytest.raises(ValidationFailedError) as exc:
        CreateLegacyBaselineDraft(
            context=CommandContext.for_actor(active_user),
            payload={"name": "Imported", "category_code": "YOGURT"},
            migration_batch_id=batch.id,
            business_no_fallback="IMP-ROW",
        ).execute()
    assert "IMPORT_ROW_REQUIRED" in exc.value.details["blocks"]


def test_import_batch_draft_is_idempotent_for_the_same_locked_row(
    active_user: User,
    organization: Organization,
    grant_action: Callable[..., None],
) -> None:
    from apps.products.models import (
        ImportBatch,
        ImportBatchStatus,
        ImportItem,
        ImportItemStatus,
        ProductChangeSet,
    )

    grant_action(active_user, "migration.confirm", "migration")
    batch = ImportBatch.objects.create(
        organization=organization,
        template_version="v1",
        status=ImportBatchStatus.PARSED,
        created_by=active_user,
        total_count=1,
    )
    from apps.products.models import ImportItemDecision

    payload = {"name": "Imported", "category_code": "YOGURT"}
    ImportItem.objects.create(
        organization=organization,
        batch=batch,
        row_number=1,
        raw_row_digest="c" * 64,
        normalized_payload=payload,
        item_status=ImportItemStatus.VALID,
        decision=ImportItemDecision.CREATE,
    )
    first = CreateLegacyBaselineDraft(
        context=CommandContext.for_actor(active_user),
        payload=payload,
        migration_batch_id=batch.id,
        import_row_number=1,
        business_no_fallback="IMP-IDEM-1",
    ).execute()
    second = CreateLegacyBaselineDraft(
        context=CommandContext.for_actor(active_user),
        payload=payload,
        migration_batch_id=batch.id,
        import_row_number=1,
        business_no_fallback="IMP-IDEM-2",
    ).execute()
    assert second.created is False
    assert second.change_set.public_id == first.change_set.public_id
    assert (
        ProductChangeSet.objects.filter(
            migration_batch_id=batch.id,
            change_type="LEGACY_BASELINE",
        ).count()
        == 1
    )


def test_import_batch_draft_rejects_undecided_or_invalid_rows(
    active_user: User,
    organization: Organization,
    grant_action: Callable[..., None],
) -> None:
    from apps.platform.api.errors import ValidationFailedError
    from apps.products.models import (
        ImportBatch,
        ImportBatchStatus,
        ImportItem,
        ImportItemDecision,
        ImportItemStatus,
    )

    grant_action(active_user, "migration.confirm", "migration")
    batch = ImportBatch.objects.create(
        organization=organization,
        template_version="v1",
        status=ImportBatchStatus.PARSED,
        created_by=active_user,
        total_count=3,
    )
    payload = {"name": "Imported", "category_code": "YOGURT"}
    cases = (
        (1, ImportItemStatus.INVALID, ImportItemDecision.CREATE, "IMPORT_ROW_NOT_READY"),
        (2, ImportItemStatus.PENDING, ImportItemDecision.CREATE, "IMPORT_ROW_NOT_READY"),
        (
            3,
            ImportItemStatus.DUPLICATE_REVIEW,
            ImportItemDecision.PENDING,
            "IMPORT_DECISION_REQUIRED",
        ),
    )
    for row_number, status, decision, block in cases:
        ImportItem.objects.create(
            organization=organization,
            batch=batch,
            row_number=row_number,
            raw_row_digest=f"{row_number}" * 64,
            normalized_payload=payload,
            item_status=status,
            decision=decision,
        )
        with pytest.raises(ValidationFailedError) as exc:
            CreateLegacyBaselineDraft(
                context=CommandContext.for_actor(active_user),
                payload=payload,
                migration_batch_id=batch.id,
                import_row_number=row_number,
                business_no_fallback=f"IMP-BAD-{row_number}",
            ).execute()
        assert block in exc.value.details["blocks"]


def test_import_batch_draft_persists_implicit_create_decision(
    active_user: User,
    organization: Organization,
    grant_action: Callable[..., None],
) -> None:
    from apps.products.models import (
        ImportBatch,
        ImportBatchStatus,
        ImportItem,
        ImportItemDecision,
        ImportItemStatus,
    )

    grant_action(active_user, "migration.confirm", "migration")
    batch = ImportBatch.objects.create(
        organization=organization,
        template_version="v1",
        status=ImportBatchStatus.PARSED,
        created_by=active_user,
        total_count=1,
    )
    payload = {"name": "Imported", "category_code": "YOGURT"}
    item = ImportItem.objects.create(
        organization=organization,
        batch=batch,
        row_number=1,
        raw_row_digest="d" * 64,
        normalized_payload=payload,
        item_status=ImportItemStatus.VALID,
        decision=ImportItemDecision.PENDING,
    )
    CreateLegacyBaselineDraft(
        context=CommandContext.for_actor(active_user),
        payload=payload,
        migration_batch_id=batch.id,
        import_row_number=1,
        business_no_fallback="IMP-IMPLICIT",
    ).execute()
    item.refresh_from_db()
    assert item.decision == ImportItemDecision.CREATE


def test_legacy_link_refuses_cross_organization_existing_product(
    active_user: User,
    grant_action: Callable[..., None],
) -> None:
    from apps.identity.models.organization import Organization as Org
    from apps.products.models import ProductLifecycleStatus, ProductSourceType

    grant_action(active_user, "legacy_baseline.draft.create", "product_change_set")
    foreign_org = Org.objects.create(name="Other Org")
    foreign_product = ProductAsset.objects.create(
        organization=foreign_org,
        business_no="FOREIGN-1",
        name="Foreign",
        category_code="YOGURT",
        source_type=ProductSourceType.LEGACY_IMPORT,
        lifecycle_status=ProductLifecycleStatus.DEVELOPING,
        product_owner=active_user,
    )
    with pytest.raises(PermissionDeniedError):
        CreateLegacyBaselineDraft(
            context=CommandContext.for_actor(active_user),
            payload={"name": "Link", "category_code": "YOGURT"},
            idempotency_key="link-cross-org",
            existing_product=foreign_product,
        ).execute()


def test_material_list_redacts_high_sensitivity_fields_for_low_clearance(
    organization: Organization,
    active_user: User,
    product_asset: ProductAsset,
    controlled_version,
    grant_action: Callable[..., None],
) -> None:
    grant_action(active_user, "product_material.completeness.read", "product_material")
    grant_action(active_user, "document.version.download", "document.version")
    action = PermissionAction.objects.get(action_code="document.version.download")
    role = Role.objects.get(role_code="ROLE_DOCUMENT_VERSION_DOWNLOAD")
    RolePermission.objects.filter(role=role, action=action).update(
        max_data_level=DataSensitivityLevel.INTERNAL
    )

    version = controlled_version(sensitivity="HIGHLY_SENSITIVE")
    ProductMaterial.objects.create(
        organization=organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=product_asset.id,
        material_type_code="PRODUCT_LABEL",
        document_version=version,
        sensitivity_level="HIGHLY_SENSITIVE",
        version_no=1,
        current_slot=1,
    )

    client = APIClient()
    client.force_authenticate(active_user)
    response = client.get(reverse("product-material-list", args=[product_asset.public_id]))
    assert response.status_code == 200
    current = response.json()["items"][0]["current"]
    assert current["sensitivity_level"] == "HIGHLY_SENSITIVE"
    assert "original_filename" not in current
    assert "document_version_public_id" not in current
