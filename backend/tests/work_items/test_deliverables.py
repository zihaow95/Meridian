"""Deliverable tiers, revisions, and file binding rules (EXE-005)."""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.documents.models import (
    Document,
    DocumentSource,
    DocumentStatus,
    DocumentVersion,
    FileObject,
    StorageBackend,
    StorageStatus,
    VersionStatus,
)
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.work_items.errors import (
    CoreDeliverableProtected,
    InactiveFileObject,
    DeliverableRevisionConflict,
)
from apps.work_items.models import (
    Deliverable,
    DeliverableRevision,
    DeliverableRevisionStatus,
    DeliverableStatus,
    DeliverableTier,
)
from apps.work_items.services.deliverables import (
    CreateDeliverableRevision,
    ExemptDeliverable,
    VoidDeliverable,
)


def _active_document_version(*, organization, actor: User, sha: str | None = None) -> DocumentVersion:
    digest = sha or hashlib.sha256(uuid4().bytes).hexdigest()
    file_object = FileObject.objects.create(
        organization=organization,
        storage_backend=StorageBackend.NAS_NFS,
        object_key=f"objects/{digest}.pdf",
        size_bytes=12,
        sha256=digest,
        detected_mime_type="application/pdf",
        storage_status=StorageStatus.ACTIVE,
    )
    document = Document.objects.create(
        organization=organization,
        document_code=f"DOC-{uuid4().hex[:8]}",
        title="Deliverable file",
        source=DocumentSource.PROJECT,
        status=DocumentStatus.ACTIVE,
    )
    return DocumentVersion.objects.create(
        organization=organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename="spec.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.DRAFT,
        uploaded_by=actor,
        uploaded_at=timezone.now(),
    )


@pytest.fixture
def core_deliverable(project: Project) -> Deliverable:
    return Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        deliverable_code="D1-CORE-DEL",
        name="Core spec",
        tier=DeliverableTier.CORE_REQUIRED,
        status=DeliverableStatus.NOT_STARTED,
        requires_professional_confirmation=True,
    )


@pytest.fixture
def custom_deliverable(project: Project) -> Deliverable:
    return Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        deliverable_code="D1-CUSTOM-DEL",
        name="Custom note",
        tier=DeliverableTier.PROJECT_CUSTOM,
        status=DeliverableStatus.DRAFT,
        requires_professional_confirmation=False,
    )


@pytest.mark.django_db
def test_core_deliverable_cannot_void_without_exemption(
    core_deliverable: Deliverable,
    project: Project,
) -> None:
    with pytest.raises(CoreDeliverableProtected):
        VoidDeliverable(
            context=CommandContext.for_actor(project.leader),
            deliverable_public_id=core_deliverable.public_id,
        ).execute()
    core_deliverable.refresh_from_db()
    assert core_deliverable.status != DeliverableStatus.VOIDED


@pytest.mark.django_db
def test_core_deliverable_can_be_exempted(
    core_deliverable: Deliverable,
    project: Project,
) -> None:
    updated = ExemptDeliverable(
        context=CommandContext.for_actor(project.leader),
        deliverable_public_id=core_deliverable.public_id,
        reason="Covered by reuse package",
    ).execute()
    assert updated.status == DeliverableStatus.EXEMPTED


@pytest.mark.django_db
def test_custom_deliverable_can_be_voided(
    custom_deliverable: Deliverable,
    project: Project,
) -> None:
    updated = VoidDeliverable(
        context=CommandContext.for_actor(project.leader),
        deliverable_public_id=custom_deliverable.public_id,
    ).execute()
    assert updated.status == DeliverableStatus.VOIDED


@pytest.mark.django_db
def test_inactive_file_object_rejects_revision(
    core_deliverable: Deliverable,
    project: Project,
    active_user: User,
) -> None:
    version = _active_document_version(
        organization=project.organization,
        actor=active_user,
    )
    version.file_object.storage_status = StorageStatus.PENDING
    version.file_object.save(update_fields=["storage_status"])
    with pytest.raises(InactiveFileObject):
        CreateDeliverableRevision(
            context=CommandContext.for_actor(project.leader),
            deliverable_public_id=core_deliverable.public_id,
            document_version_public_id=version.public_id,
        ).execute()


@pytest.mark.django_db
def test_revision_numbers_increment_and_lock_on_submit(
    core_deliverable: Deliverable,
    project: Project,
    active_user: User,
    grant_action,
) -> None:
    from apps.work_items.services.deliverables import SubmitRevisionForConfirmation

    grant_action(project.leader, "revision.submit", "deliverable_revision", role_code="LEADER")
    grant_action(project.leader, "deliverable.create", "deliverable", role_code="LEADER")
    first_doc = _active_document_version(organization=project.organization, actor=active_user)
    second_doc = _active_document_version(organization=project.organization, actor=active_user)
    first = CreateDeliverableRevision(
        context=CommandContext.for_actor(project.leader),
        deliverable_public_id=core_deliverable.public_id,
        document_version_public_id=first_doc.public_id,
    ).execute()
    second = CreateDeliverableRevision(
        context=CommandContext.for_actor(project.leader),
        deliverable_public_id=core_deliverable.public_id,
        document_version_public_id=second_doc.public_id,
    ).execute()
    assert first.revision_number == 1
    assert second.revision_number == 2
    submitted = SubmitRevisionForConfirmation(
        context=CommandContext.for_actor(project.leader),
        revision_public_id=second.public_id,
        confirmer_public_id=active_user.public_id,
    ).execute()
    assert submitted.status == DeliverableRevisionStatus.LOCKED
    assert (
        DeliverableRevision.objects.filter(
            deliverable=core_deliverable,
            revision_number=2,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_create_revision_rolls_back_when_audit_fails(
    core_deliverable: Deliverable,
    project: Project,
    active_user: User,
    monkeypatch,
) -> None:
    grant_ready = project.leader
    version = _active_document_version(organization=project.organization, actor=active_user)

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("audit failed")

    monkeypatch.setattr(
        "apps.work_items.services.deliverables.append_event",
        _boom,
    )
    with pytest.raises(RuntimeError, match="audit failed"):
        CreateDeliverableRevision(
            context=CommandContext.for_actor(grant_ready),
            deliverable_public_id=core_deliverable.public_id,
            document_version_public_id=version.public_id,
        ).execute()
    assert DeliverableRevision.objects.filter(deliverable=core_deliverable).count() == 0
