"""Pilot service-layer authorization denials."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from apps.authorization.models.role import (
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
)
from apps.documents.models import DocumentSource, DocumentVersion, StorageStatus, VersionStatus
from apps.documents.services.ingest import activate_staged_content, stage_controlled_content
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User
from apps.pilot.errors import PilotValidationError
from apps.pilot.services.batches import AddPilotParticipant, CreatePilotBatch, StartPilotBatch
from apps.pilot.services.feedback import OpenPilotFeedback
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext

pytestmark = pytest.mark.django_db


def _controlled_version(
    *,
    organization: Organization,
    actor: User,
    sensitivity: str = "INTERNAL",
    status: str = VersionStatus.CONTROLLED,
) -> DocumentVersion:
    storage = get_file_storage()
    content = b"%PDF-1.4 evidence-deny"
    temp_path = storage.temp_dir() / f"{uuid4()}.part"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path.write_bytes(content)
    _, staged = stage_controlled_content(
        organization=organization,
        source_temp_path=Path(temp_path),
        sha256=sha256(content).hexdigest(),
        size_bytes=len(content),
        original_filename="evidence.pdf",
        mime_type="application/pdf",
        uploaded_by=actor,
        source=DocumentSource.MIGRATION,
        sensitivity_level=sensitivity,
    )
    version = activate_staged_content(staged, storage)
    DocumentVersion.objects.filter(pk=version.pk).update(
        sensitivity_level=sensitivity,
        status=status,
    )
    version.file_object.storage_status = StorageStatus.ACTIVE
    version.file_object.save(update_fields=["storage_status"])
    version.refresh_from_db()
    return version


def test_create_batch_refuses_actor_without_manage_action(another_active_user: User) -> None:
    with pytest.raises(PermissionDeniedError):
        CreatePilotBatch(
            context=CommandContext.for_actor(another_active_user),
            name="Denied batch",
        ).execute()


def test_open_feedback_refuses_non_controlled_evidence(
    active_user: User,
    another_active_user: User,
    organization: Organization,
) -> None:
    ctx = CommandContext.for_actor(active_user)
    batch = CreatePilotBatch(context=ctx, name="Draft evidence").execute()
    AddPilotParticipant(
        context=ctx,
        batch_public_id=batch.public_id,
        user_public_id=another_active_user.public_id,
    ).execute()
    StartPilotBatch(context=ctx, batch_public_id=batch.public_id).execute()
    version = _controlled_version(
        organization=organization,
        actor=active_user,
        status=VersionStatus.DRAFT,
    )

    with pytest.raises(PilotValidationError):
        OpenPilotFeedback(
            context=ctx,
            batch_public_id=batch.public_id,
            title="Bad evidence",
            reproduction_summary="Draft attachment",
            evidence_document_version_public_id=version.public_id,
        ).execute()


def test_open_feedback_refuses_evidence_above_actor_clearance(
    active_user: User,
    another_active_user: User,
    organization: Organization,
    grant_action: Callable[..., None],
) -> None:
    grant_action(another_active_user, "pilot.feedback.create", "pilot.feedback")
    grant_action(another_active_user, "document.version.download", "document.version")
    action = PermissionAction.objects.get(action_code="document.version.download")
    role = Role.objects.get(role_code="ROLE_DOCUMENT_VERSION_DOWNLOAD")
    RolePermission.objects.filter(role=role, action=action).update(
        max_data_level=DataSensitivityLevel.INTERNAL
    )

    manager_ctx = CommandContext.for_actor(active_user)
    batch = CreatePilotBatch(context=manager_ctx, name="Sensitive evidence").execute()
    AddPilotParticipant(
        context=manager_ctx,
        batch_public_id=batch.public_id,
        user_public_id=another_active_user.public_id,
    ).execute()
    StartPilotBatch(context=manager_ctx, batch_public_id=batch.public_id).execute()
    version = _controlled_version(
        organization=organization,
        actor=active_user,
        sensitivity="HIGHLY_SENSITIVE",
    )

    with pytest.raises(PermissionDeniedError):
        OpenPilotFeedback(
            context=CommandContext.for_actor(another_active_user),
            batch_public_id=batch.public_id,
            title="Needs evidence",
            reproduction_summary="Sensitive attachment",
            evidence_document_version_public_id=version.public_id,
        ).execute()
