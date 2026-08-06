"""Historical materials land in a staging queue, never as approved materials."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.documents.models import DocumentSource, DocumentVersion
from apps.documents.services.ingest import activate_staged_content, stage_controlled_content
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.products.models import (
    AttributeOwnerType,
    LegacyMaterialStatus,
    LegacyMaterialSubmission,
    MaterialStatus,
    ProductMaterial,
)
from apps.products.services.legacy_material_intake import CreateLegacyMaterialSubmission

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.4 legacy"


@pytest.fixture(autouse=True)
def _grant_intake(active_user: User, grant_action) -> None:
    grant_action(active_user, "legacy_material.submission.create", "legacy_material_submission")


@pytest.fixture
def controlled_version(organization: Organization, active_user: User):
    storage = get_file_storage()

    def _create(content: bytes = PDF_BYTES) -> DocumentVersion:
        temp_path = storage.temp_dir() / f"{uuid4()}.part"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content)
        _, staged = stage_controlled_content(
            organization=organization,
            source_temp_path=Path(temp_path),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            original_filename="legacy-label.pdf",
            mime_type="application/pdf",
            uploaded_by=active_user,
            source=DocumentSource.MIGRATION,
            catalog_item_code="PRODUCT_LABEL",
        )
        return activate_staged_content(staged, storage)

    return _create


def submit(
    *,
    actor: User,
    version: DocumentVersion,
    owner_id,
    idempotency_key: str = "intake-1",
    **claimed: object,
):
    return CreateLegacyMaterialSubmission(
        context=CommandContext.for_actor(actor),
        document_version_public_id=version.public_id,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=owner_id,
        idempotency_key=idempotency_key,
        source_note=claimed.pop("source_note", "从旧共享盘导出"),
        original_file_date=claimed.pop("original_file_date", date(2019, 5, 20)),
        claimed_version=claimed.pop("claimed_version", "V3"),
        claimed_effective_from=claimed.pop("claimed_effective_from", date(2019, 6, 1)),
    ).execute()


def test_a_submission_records_the_provenance_the_reviewer_will_need(
    active_user: User, controlled_version
) -> None:
    version = controlled_version()

    result = submit(actor=active_user, version=version, owner_id=101)

    submission = result.submission
    assert submission.source_note == "从旧共享盘导出"
    assert submission.original_file_date == date(2019, 5, 20)
    assert submission.submitted_by_id == active_user.id
    assert submission.sha256 == version.file_object.sha256
    assert submission.claimed_version == "V3"
    assert submission.claimed_effective_from == date(2019, 6, 1)
    assert submission.processing_status == LegacyMaterialStatus.PENDING_TRIAGE


def test_the_intake_does_not_touch_the_stored_bytes(active_user: User, controlled_version) -> None:
    version = controlled_version()
    digest_before = version.file_object.sha256

    submit(actor=active_user, version=version, owner_id=101)

    version.file_object.refresh_from_db()
    assert version.file_object.sha256 == digest_before
    assert version.file_object.size_bytes == len(PDF_BYTES)


def test_retrying_the_same_idempotency_key_keeps_one_submission(
    active_user: User, controlled_version
) -> None:
    version = controlled_version()

    first = submit(actor=active_user, version=version, owner_id=101)
    second = submit(actor=active_user, version=version, owner_id=101)

    assert first.submission.public_id == second.submission.public_id
    assert LegacyMaterialSubmission.objects.count() == 1


def test_the_database_refuses_a_second_row_with_the_same_idempotency_key(
    organization: Organization, active_user: User, controlled_version
) -> None:
    version = controlled_version()
    submit(actor=active_user, version=version, owner_id=101)

    with pytest.raises(IntegrityError), transaction.atomic():
        LegacyMaterialSubmission.objects.create(
            organization=organization,
            document_version=version,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=202,
            submitted_by=active_user,
            sha256=version.file_object.sha256,
            idempotency_key="intake-1",
        )


def test_the_same_file_under_a_different_owner_is_flagged_as_a_duplicate_candidate(
    active_user: User, controlled_version
) -> None:
    version = controlled_version()
    submit(actor=active_user, version=version, owner_id=101, idempotency_key="a")

    result = submit(actor=active_user, version=version, owner_id=202, idempotency_key="b")

    assert [candidate.owner_id for candidate in result.duplicate_candidates] == [101]


def test_a_first_submission_has_no_duplicate_candidates(
    active_user: User, controlled_version
) -> None:
    result = submit(actor=active_user, version=controlled_version(), owner_id=101)

    assert result.duplicate_candidates == []


def test_staging_a_material_creates_no_product_material(
    active_user: User, controlled_version
) -> None:
    submit(actor=active_user, version=controlled_version(), owner_id=101)

    assert not ProductMaterial.objects.exists()
    assert not ProductMaterial.objects.filter(material_status=MaterialStatus.APPROVED).exists()


def test_the_intake_is_audited_without_copying_the_file_content(
    active_user: User, controlled_version
) -> None:
    version = controlled_version()

    result = submit(actor=active_user, version=version, owner_id=101)

    event = AuditEvent.objects.get(action_code="legacy_material.submission.create")
    assert event.resource_public_id == result.submission.public_id
    assert PDF_BYTES.decode("latin-1") not in str(event.after_summary)
    assert event.after_summary["sha256"] == version.file_object.sha256
