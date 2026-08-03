"""Historical files become product materials only through verification.

The queue from task 6.2 holds bytes and claims. Turning those into a material
history means someone vouched for the source, the order and the effect, so the
chain service refuses anything the verification service did not sign off.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.documents.models import DocumentSource, DocumentVersion
from apps.documents.services.ingest import activate_staged_content, stage_controlled_content
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    AttributeOwnerType,
    LegacyMaterialStatus,
    LegacyMaterialSubmission,
    MaterialStatus,
    ProductMaterial,
)
from apps.products.services.legacy_material_intake import CreateLegacyMaterialSubmission
from apps.products.services.material_chains import (
    CreateLegacyMaterialVersionChain,
    MaterialChainRejected,
    MaterialOwner,
    VerifyLegacyMaterialSubmission,
)

pytestmark = pytest.mark.django_db

OWNER_ID = 4242
MATERIAL_TYPE = "PRODUCT_LABEL"


@pytest.fixture
def staged_version(organization: Organization, active_user: User) -> Callable[..., DocumentVersion]:
    storage = get_file_storage()

    def _create(marker: str) -> DocumentVersion:
        content = f"%PDF-1.4 {marker}".encode()
        temp_path = storage.temp_dir() / f"{uuid4()}.part"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(content)
        _, staged = stage_controlled_content(
            organization=organization,
            source_temp_path=Path(temp_path),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            original_filename=f"{marker}.pdf",
            mime_type="application/pdf",
            uploaded_by=active_user,
            source=DocumentSource.MIGRATION,
            catalog_item_code=MATERIAL_TYPE,
        )
        return activate_staged_content(staged, storage)

    return _create


@pytest.fixture
def submitter(active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(active_user, "legacy_material.submission.create", "legacy_material_submission")
    grant_action(active_user, "product_material.manage", "product_material")
    return active_user


@pytest.fixture
def verifier(another_active_user: User, grant_action: Callable[..., None]) -> User:
    grant_action(
        another_active_user,
        "legacy_material.submission.verify",
        "legacy_material_submission",
    )
    return another_active_user


@pytest.fixture
def submissions(
    submitter: User, staged_version: Callable[..., DocumentVersion]
) -> Callable[[str, date], LegacyMaterialSubmission]:
    def _create(marker: str, effective_from: date) -> LegacyMaterialSubmission:
        return (
            CreateLegacyMaterialSubmission(
                context=CommandContext.for_actor(submitter),
                document_version_public_id=staged_version(marker).public_id,
                owner_type=AttributeOwnerType.PRODUCT,
                owner_id=OWNER_ID,
                idempotency_key=f"intake-{marker}",
                source_note="旧共享盘",
                original_file_date=effective_from,
                claimed_version=marker,
                claimed_effective_from=effective_from,
            )
            .execute()
            .submission
        )

    return _create


def verify(actor: User, submission: LegacyMaterialSubmission) -> LegacyMaterialSubmission:
    return VerifyLegacyMaterialSubmission(
        context=CommandContext.for_actor(actor),
        submission_public_id=submission.public_id,
        decision=LegacyMaterialStatus.VERIFIED,
        note="核对了原件与生效日期",
    ).execute()


def build_chain(actor: User, ordered, current) -> list[ProductMaterial]:
    return CreateLegacyMaterialVersionChain(
        context=CommandContext.for_actor(actor),
        ordered_submission_ids=[submission.public_id for submission in ordered],
        current_submission_id=current.public_id,
        owner=MaterialOwner(owner_type=AttributeOwnerType.PRODUCT, owner_id=OWNER_ID),
        material_type_code=MATERIAL_TYPE,
    ).execute()


def test_verification_records_who_vouched_for_the_file_and_when(
    submissions, verifier: User
) -> None:
    submission = submissions("V1", date(2019, 1, 1))

    verified = verify(verifier, submission)

    assert verified.processing_status == LegacyMaterialStatus.VERIFIED
    assert verified.verified_by_id == verifier.id
    assert verified.verified_at is not None
    assert verified.verification_note == "核对了原件与生效日期"


def test_verification_requires_the_verify_action(submissions, submitter: User) -> None:
    submission = submissions("V1", date(2019, 1, 1))

    with pytest.raises(PermissionDeniedError):
        verify(submitter, submission)

    submission.refresh_from_db()
    assert submission.processing_status == LegacyMaterialStatus.PENDING_TRIAGE


def test_verification_writes_an_audit_event(submissions, verifier: User) -> None:
    submission = submissions("V1", date(2019, 1, 1))

    verify(verifier, submission)

    assert AuditEvent.objects.filter(
        action_code="legacy_material.submission.verify",
        resource_public_id=submission.public_id,
    ).exists()


def test_the_chain_follows_the_order_the_reviewer_gave(
    submissions, verifier: User, submitter: User
) -> None:
    old = verify(verifier, submissions("V1", date(2019, 1, 1)))
    middle = verify(verifier, submissions("V2", date(2020, 1, 1)))
    newest = verify(verifier, submissions("V3", date(2021, 1, 1)))

    materials = build_chain(submitter, [old, middle, newest], newest)

    assert [material.version_no for material in materials] == [1, 2, 3]
    assert materials[0].supersedes_material_id is None
    assert materials[1].supersedes_material_id == materials[0].id
    assert materials[2].supersedes_material_id == materials[1].id
    assert [material.source_submission_id for material in materials] == [
        old.id,
        middle.id,
        newest.id,
    ]


def test_only_the_nominated_submission_is_the_current_material(
    submissions, verifier: User, submitter: User
) -> None:
    old = verify(verifier, submissions("V1", date(2019, 1, 1)))
    newest = verify(verifier, submissions("V2", date(2020, 1, 1)))

    materials = build_chain(submitter, [old, newest], newest)

    assert [material.current_slot for material in materials] == [None, 1]
    assert [material.material_status for material in materials] == [
        MaterialStatus.INACTIVE,
        MaterialStatus.DRAFT,
    ]


def test_promotion_never_marks_a_material_approved_on_its_own(
    submissions, verifier: User, submitter: User
) -> None:
    """Verified provenance is not professional confirmation."""

    newest = verify(verifier, submissions("V1", date(2019, 1, 1)))

    materials = build_chain(submitter, [newest], newest)

    assert materials[0].material_status == MaterialStatus.DRAFT
    assert materials[0].confirmations.count() == 0


def test_promoted_material_inherits_document_version_sensitivity(
    submissions, verifier: User, submitter: User
) -> None:
    newest = verify(verifier, submissions("V1", date(2019, 1, 1)))
    DocumentVersion.objects.filter(pk=newest.document_version_id).update(
        sensitivity_level="HIGHLY_SENSITIVE"
    )
    newest.document_version.refresh_from_db()

    materials = build_chain(submitter, [newest], newest)

    assert materials[0].sensitivity_level == "HIGHLY_SENSITIVE"


def test_a_submission_still_in_triage_cannot_be_promoted(submissions, submitter: User) -> None:
    pending = submissions("V1", date(2019, 1, 1))

    with pytest.raises(MaterialChainRejected):
        build_chain(submitter, [pending], pending)

    assert ProductMaterial.objects.count() == 0


def test_a_submission_cannot_be_chained_onto_a_different_owner(
    submissions, verifier: User, submitter: User
) -> None:
    verified = verify(verifier, submissions("V1", date(2019, 1, 1)))

    with pytest.raises(MaterialChainRejected, match="different business object"):
        CreateLegacyMaterialVersionChain(
            context=CommandContext.for_actor(submitter),
            ordered_submission_ids=[verified.public_id],
            current_submission_id=verified.public_id,
            owner=MaterialOwner(owner_type=AttributeOwnerType.PRODUCT, owner_id=OWNER_ID + 999),
            material_type_code=MATERIAL_TYPE,
        ).execute()


def test_a_submission_catalog_must_match_the_requested_material_type(
    submissions, verifier: User, submitter: User
) -> None:
    verified = verify(verifier, submissions("V1", date(2019, 1, 1)))

    with pytest.raises(MaterialChainRejected, match="catalog item"):
        CreateLegacyMaterialVersionChain(
            context=CommandContext.for_actor(submitter),
            ordered_submission_ids=[verified.public_id],
            current_submission_id=verified.public_id,
            owner=MaterialOwner(owner_type=AttributeOwnerType.PRODUCT, owner_id=OWNER_ID),
            material_type_code="MARKETING_IMAGE",
        ).execute()


def test_a_hand_flipped_status_is_not_accepted_as_verification(
    submissions, submitter: User
) -> None:
    """Skipping the verification service leaves no verifier, so promotion fails."""

    forged = submissions("V1", date(2019, 1, 1))
    LegacyMaterialSubmission.objects.filter(pk=forged.pk).update(
        processing_status=LegacyMaterialStatus.VERIFIED
    )
    forged.refresh_from_db()

    with pytest.raises(MaterialChainRejected):
        build_chain(submitter, [forged], forged)


def test_a_rejected_submission_cannot_be_promoted(
    submissions, verifier: User, submitter: User
) -> None:
    rejected = VerifyLegacyMaterialSubmission(
        context=CommandContext.for_actor(verifier),
        submission_public_id=submissions("V1", date(2019, 1, 1)).public_id,
        decision=LegacyMaterialStatus.REJECTED,
        note="来源无法证明",
    ).execute()

    with pytest.raises(MaterialChainRejected):
        build_chain(submitter, [rejected], rejected)


def test_the_current_submission_must_be_part_of_the_chain(
    submissions, verifier: User, submitter: User
) -> None:
    inside = verify(verifier, submissions("V1", date(2019, 1, 1)))
    outside = verify(verifier, submissions("V2", date(2020, 1, 1)))

    with pytest.raises(MaterialChainRejected):
        build_chain(submitter, [inside], outside)


def test_a_later_chain_moves_the_current_marker_forward(
    submissions, verifier: User, submitter: User
) -> None:
    first = verify(verifier, submissions("V1", date(2019, 1, 1)))
    build_chain(submitter, [first], first)

    later = verify(verifier, submissions("V2", date(2020, 1, 1)))
    appended = build_chain(submitter, [later], later)

    assert appended[0].version_no == 2
    assert appended[0].supersedes_material_id is not None
    current = ProductMaterial.objects.filter(current_slot=1)
    assert [material.id for material in current] == [appended[0].id]


def test_database_refuses_two_current_materials_for_one_owner_and_type(
    submissions, verifier: User, submitter: User, organization: Organization
) -> None:
    first = verify(verifier, submissions("V1", date(2019, 1, 1)))
    materials = build_chain(submitter, [first], first)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProductMaterial.objects.create(
            organization=organization,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=OWNER_ID,
            material_type_code=MATERIAL_TYPE,
            document_version=materials[0].document_version,
            version_no=99,
            current_slot=1,
        )


def test_database_refuses_a_repeated_version_number_in_one_chain(
    submissions, verifier: User, submitter: User, organization: Organization
) -> None:
    first = verify(verifier, submissions("V1", date(2019, 1, 1)))
    materials = build_chain(submitter, [first], first)

    with pytest.raises(IntegrityError), transaction.atomic():
        ProductMaterial.objects.create(
            organization=organization,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=OWNER_ID,
            material_type_code=MATERIAL_TYPE,
            document_version=materials[0].document_version,
            version_no=materials[0].version_no,
            current_slot=None,
        )


def test_building_a_chain_requires_the_manage_action(
    submissions, verifier: User, another_active_user: User
) -> None:
    verified = verify(verifier, submissions("V1", date(2019, 1, 1)))

    with pytest.raises(PermissionDeniedError):
        build_chain(another_active_user, [verified], verified)


def test_promotion_marks_the_submission_as_used(
    submissions, verifier: User, submitter: User
) -> None:
    verified = verify(verifier, submissions("V1", date(2019, 1, 1)))

    materials = build_chain(submitter, [verified], verified)

    verified.refresh_from_db()
    assert verified.promoted_material_id == materials[0].id


def test_a_submission_cannot_be_promoted_twice(
    submissions, verifier: User, submitter: User
) -> None:
    verified = verify(verifier, submissions("V1", date(2019, 1, 1)))
    build_chain(submitter, [verified], verified)

    with pytest.raises(MaterialChainRejected):
        build_chain(submitter, [verified], verified)


def test_the_chain_write_is_audited_once_per_material(
    submissions, verifier: User, submitter: User
) -> None:
    old = verify(verifier, submissions("V1", date(2019, 1, 1)))
    newest = verify(verifier, submissions("V2", date(2020, 1, 1)))

    materials = build_chain(submitter, [old, newest], newest)

    audited = set(
        AuditEvent.objects.filter(action_code="product_material.promote").values_list(
            "resource_public_id", flat=True
        )
    )
    assert audited == {material.public_id for material in materials}


def test_verifying_twice_keeps_the_first_decision(submissions, verifier: User) -> None:
    submission = submissions("V1", date(2019, 1, 1))
    first = verify(verifier, submission)
    decided_at = first.verified_at

    with pytest.raises(MaterialChainRejected):
        VerifyLegacyMaterialSubmission(
            context=CommandContext.for_actor(verifier),
            submission_public_id=submission.public_id,
            decision=LegacyMaterialStatus.REJECTED,
            note="改主意了",
        ).execute()

    submission.refresh_from_db()
    assert submission.processing_status == LegacyMaterialStatus.VERIFIED
    assert submission.verified_at == decided_at


def test_verification_note_is_kept_for_the_audit_trail(submissions, verifier: User) -> None:
    submission = submissions("V1", date(2019, 1, 1))

    verified = verify(verifier, submission)

    event = AuditEvent.objects.get(
        action_code="legacy_material.submission.verify",
        resource_public_id=submission.public_id,
    )
    assert event.after_summary["processing_status"] == LegacyMaterialStatus.VERIFIED
    assert event.after_summary["verified_by_public_id"] == str(verifier.public_id)
    assert timezone.is_aware(verified.verified_at)
