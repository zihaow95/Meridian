"""Professional confirmation bound to a concrete revision (EXE-006)."""

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
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.models import Project
from apps.work_items.models import (
    Deliverable,
    DeliverableRevisionStatus,
    DeliverableStatus,
    DeliverableTier,
    ProfessionalConfirmation,
    ProfessionalConfirmationStatus,
)
from apps.work_items.services.deliverables import (
    CreateDeliverableRevision,
    SubmitRevisionForConfirmation,
)
from apps.work_items.services.professional_confirmations import DecideProfessionalConfirmation


def _doc_version(*, organization, actor: User) -> DocumentVersion:
    digest = hashlib.sha256(uuid4().bytes).hexdigest()
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
        title="Confirmable",
        source=DocumentSource.PROJECT,
        status=DocumentStatus.ACTIVE,
    )
    return DocumentVersion.objects.create(
        organization=organization,
        document=document,
        version_number=1,
        file_object=file_object,
        original_filename="confirm.pdf",
        declared_mime_type="application/pdf",
        detected_mime_type="application/pdf",
        status=VersionStatus.DRAFT,
        uploaded_by=actor,
        uploaded_at=timezone.now(),
    )


@pytest.fixture
def confirmer(organization, grant_action) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Confirmer",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(
        user,
        "professional_confirmation.decide",
        "professional_confirmation",
        role_code="CONFIRMER",
    )
    return user


@pytest.fixture
def deliverable(project: Project) -> Deliverable:
    return Deliverable.objects.create(
        organization=project.organization,
        project=project,
        stage=project.stages.get(stage_code="D1"),
        deliverable_code="D1-CONF",
        name="Confirmable deliverable",
        tier=DeliverableTier.TEMPLATE_RECOMMENDED,
        status=DeliverableStatus.NOT_STARTED,
        requires_professional_confirmation=True,
    )


@pytest.mark.django_db
def test_new_revision_does_not_inherit_confirmation(
    deliverable: Deliverable,
    project: Project,
    confirmer: User,
    active_user: User,
    grant_action,
) -> None:
    grant_action(project.leader, "revision.submit", "deliverable_revision", role_code="LEADER")
    grant_action(project.leader, "deliverable.create", "deliverable", role_code="LEADER")
    first_doc = _doc_version(organization=project.organization, actor=active_user)
    second_doc = _doc_version(organization=project.organization, actor=active_user)
    first = CreateDeliverableRevision(
        context=CommandContext.for_actor(project.leader),
        deliverable_public_id=deliverable.public_id,
        document_version_public_id=first_doc.public_id,
    ).execute()
    submitted = SubmitRevisionForConfirmation(
        context=CommandContext.for_actor(project.leader),
        revision_public_id=first.public_id,
        confirmer_public_id=confirmer.public_id,
    ).execute()
    confirmation = ProfessionalConfirmation.objects.get(deliverable_revision=submitted)
    DecideProfessionalConfirmation(
        context=CommandContext.for_actor(confirmer),
        confirmation_public_id=confirmation.public_id,
        decision=ProfessionalConfirmationStatus.APPROVED,
        comment="Looks good",
    ).execute()

    second = CreateDeliverableRevision(
        context=CommandContext.for_actor(project.leader),
        deliverable_public_id=deliverable.public_id,
        document_version_public_id=second_doc.public_id,
    ).execute()
    confirmation.refresh_from_db()
    assert confirmation.status == ProfessionalConfirmationStatus.SUPERSEDED
    assert second.status == DeliverableRevisionStatus.DRAFT
    assert not ProfessionalConfirmation.objects.filter(
        deliverable_revision=second,
        status=ProfessionalConfirmationStatus.APPROVED,
    ).exists()


@pytest.mark.django_db
def test_unauthorized_user_cannot_decide_confirmation(
    deliverable: Deliverable,
    project: Project,
    confirmer: User,
    active_user: User,
    grant_action,
) -> None:
    grant_action(project.leader, "revision.submit", "deliverable_revision", role_code="LEADER")
    grant_action(project.leader, "deliverable.create", "deliverable", role_code="LEADER")
    doc = _doc_version(organization=project.organization, actor=active_user)
    revision = CreateDeliverableRevision(
        context=CommandContext.for_actor(project.leader),
        deliverable_public_id=deliverable.public_id,
        document_version_public_id=doc.public_id,
    ).execute()
    submitted = SubmitRevisionForConfirmation(
        context=CommandContext.for_actor(project.leader),
        revision_public_id=revision.public_id,
        confirmer_public_id=confirmer.public_id,
    ).execute()
    confirmation = ProfessionalConfirmation.objects.get(deliverable_revision=submitted)
    stranger = User.objects.create_user(
        organization=project.organization,
        display_name="Stranger",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    with pytest.raises(PermissionDeniedError):
        DecideProfessionalConfirmation(
            context=CommandContext.for_actor(stranger),
            confirmation_public_id=confirmation.public_id,
            decision=ProfessionalConfirmationStatus.APPROVED,
            comment="Nope",
        ).execute()
    confirmation.refresh_from_db()
    assert confirmation.status == ProfessionalConfirmationStatus.PENDING
