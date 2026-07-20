"""In-flight project migration baselines (EXE-014)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import pytest
from django.utils import timezone

from apps.documents.storage.factory import get_file_storage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.notifications.models import Todo
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.errors import MigrationImportFailed
from apps.projects.models import (
    MigrationBaseline,
    MigrationDisposition,
    Project,
    ProjectStageStatus,
)
from apps.projects.services.confirm_migration_baseline import ConfirmMigrationBaseline
from apps.projects.services.import_migration_baseline import ImportProjectMigrationBatch
from apps.projects.services.migration_file_staging import stream_stage_migration_file
from apps.stage_gates.models import StageGateInstance
from apps.work_items.models import ProfessionalConfirmation, Task


@pytest.fixture
def migrator(organization, grant_action: Callable[..., None]) -> User:
    user = User.objects.create_user(
        organization=organization,
        display_name="Migration Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(user, "project_migration.confirm", "project", role_code="PRODUCT_DIRECTOR")
    return user


HISTORY_FILE_BYTES = b"%PDF-1.4 migrated d2 report body"
HISTORY_FILE_SHA256 = hashlib.sha256(HISTORY_FILE_BYTES).hexdigest()


def _stage_history_file(
    organization: Organization,
    *,
    filename: str = "d2-report.pdf",
    content: bytes = HISTORY_FILE_BYTES,
) -> dict[str, Any]:
    return stream_stage_migration_file(
        chunks=iter([content]),
        filename=filename,
        mime_type="application/pdf",
        storage=get_file_storage(),
        organization=organization,
    )


def _history_file_entry(staged: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "filename": staged["filename"],
        "source_note": "NAS archive",
        "source_version": "3",
        "mime_type": staged["mime_type"],
        "sha256": staged["sha256"],
        "size_bytes": staged["size_bytes"],
        "staging_relpath": staged["staging_relpath"],
        **extra,
    }


def _d3_row(
    organization: Organization,
    *,
    external_id: str = "EXT-D3-001",
    history_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if history_files is None:
        history_files = [_history_file_entry(_stage_history_file(organization))]
    return {
        "external_project_id": external_id,
        "name": "In-flight yogurt",
        "current_stage_code": "D3",
        "leader_display_name": "Legacy Leader",
        "disposition": MigrationDisposition.CONTINUE,
        "history_decision_summary": "D1/D2 approved offline before Meridian.",
        "plan_summary": {"d3_planned_end": "2026-08-01"},
        "history_tasks": [
            {"task_code": "D1-LEGACY", "name": "Legacy D1", "stage_code": "D1"},
            {"task_code": "D2-LEGACY", "name": "Legacy D2", "stage_code": "D2"},
        ],
        "history_files": history_files,
    }


@pytest.mark.django_db
def test_import_batch_is_idempotent_by_external_id(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    first = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-1",
        rows=[_d3_row(migrator.organization)],
    ).execute()
    second = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-1",
        rows=[_d3_row(migrator.organization)],
    ).execute()
    assert first.batch.public_id == second.batch.public_id
    assert MigrationBaseline.objects.filter(batch=first.batch).count() == 1
    assert first.accepted_count == 1
    assert second.accepted_count == 1


@pytest.mark.django_db
def test_unconfirmed_baseline_cannot_continue(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-unconfirmed",
        rows=[_d3_row(migrator.organization)],
    ).execute()
    baseline = imported.baselines[0]
    assert baseline.confirmed_at is None
    assert Project.objects.filter(migration_baseline=baseline).count() == 0


@pytest.mark.django_db
def test_continue_from_d3_skips_prior_gates_and_confirmations(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-d3",
        rows=[_d3_row(migrator.organization)],
    ).execute()
    baseline = imported.baselines[0]
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.CONTINUE,
        idempotency_key="confirm-d3",
    ).execute()
    project = result.project
    assert project is not None
    stage_codes = list(project.stages.order_by("sequence_no").values_list("stage_code", flat=True))
    assert stage_codes[0] == "D3"
    assert "D1" not in stage_codes
    assert "D2" not in stage_codes
    assert StageGateInstance.objects.filter(project=project, stage_code="D1").count() == 0
    assert StageGateInstance.objects.filter(project=project, stage_code="D2").count() == 0
    assert (
        ProfessionalConfirmation.objects.filter(
            deliverable_revision__deliverable__project=project
        ).count()
        == 0
    )
    assert Task.objects.filter(project=project, source_type="MIGRATED_HISTORY").count() == 2
    from apps.documents.models import DocumentVersion, FileObject, StorageStatus
    from apps.documents.storage.factory import get_file_storage
    from apps.work_items.models import Deliverable

    history_deliverable = Deliverable.objects.filter(project=project, name="d2-report.pdf").first()
    assert history_deliverable is not None
    assert history_deliverable.current_revision_id is not None
    version = DocumentVersion.objects.filter(
        pk=history_deliverable.current_revision.document_version_id
    ).first()
    assert version is not None

    # The migrated file must be a real, checksummed, ACTIVE storage object.
    file_object = FileObject.objects.get(pk=version.file_object_id)
    assert file_object.storage_status == StorageStatus.ACTIVE
    assert file_object.sha256 == HISTORY_FILE_SHA256
    assert file_object.size_bytes == len(HISTORY_FILE_BYTES)
    stored_path = get_file_storage().final_path_for(file_object.object_key)
    assert stored_path.exists()
    assert stored_path.read_bytes() == HISTORY_FILE_BYTES
    assert project.current_stage.stage_code == "D3"
    assert project.current_stage.status == ProjectStageStatus.ACTIVE


@pytest.mark.django_db
def test_history_file_without_real_content_fails_closed(
    migrator: User,
    project_template_version,
) -> None:
    """A migrated file lacking a streaming stage must fail closed on import."""

    del project_template_version
    row = _d3_row(migrator.organization, external_id="EXT-NOFILE", history_files=[])
    row["history_files"] = [{"filename": "ghost.pdf", "source_note": "no bytes"}]
    with pytest.raises(MigrationImportFailed):
        ImportProjectMigrationBatch(
            context=CommandContext.for_actor(migrator),
            batch_key="batch-nofile",
            rows=[row],
        ).execute()


@pytest.mark.django_db
def test_migrated_history_file_is_discoverable_and_downloadable(
    migrator: User,
    grant_action: Callable[..., None],
    project_template_version,
    api_client,
) -> None:
    """A migrated file must be downloadable through the workbench, not just on disk."""

    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-download",
        rows=[_d3_row(migrator.organization, external_id="EXT-DOWNLOAD")],
    ).execute()
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=imported.baselines[0].public_id,
        disposition=MigrationDisposition.CONTINUE,
        idempotency_key="confirm-download",
    ).execute()
    project = result.project
    assert project is not None

    api_client.force_authenticate(user=migrator)

    # The workbench exposes the document version so a client can discover it.
    listing = api_client.get(f"/api/v1/projects/{project.public_id}/deliverables")
    assert listing.status_code == 200
    migrated = next(row for row in listing.json()["items"] if row["name"] == "d2-report.pdf")
    version_public_id = migrated["document_version_public_id"]
    assert version_public_id is not None

    # Without the download right, the ticket request is denied.
    denied = api_client.post(f"/api/v1/documents/versions/{version_public_id}/download-ticket")
    assert denied.status_code in (403, 404)

    # With the download right, a ticket is issued and the file is served.
    grant_action(migrator, "document.version.download", "document.version")
    ticket = api_client.post(f"/api/v1/documents/versions/{version_public_id}/download-ticket")
    assert ticket.status_code == 200
    token = ticket.json()["token"]
    download = api_client.get(f"/api/v1/documents/download/{token}")
    assert download.status_code == 200


@pytest.mark.django_db
def test_resolve_migration_staging_path_rejects_traversal(
    migrator: User,
    project_template_version,
) -> None:
    """Absolute paths and .. must not resolve outside the storage temp root."""

    del migrator, project_template_version
    from apps.documents.storage.factory import get_file_storage
    from apps.projects.errors import MigrationImportFailed
    from apps.projects.services.migration_file_staging import resolve_migration_staging_path

    storage = get_file_storage()
    with pytest.raises(MigrationImportFailed):
        resolve_migration_staging_path(storage, "../secrets/passwd")
    with pytest.raises(MigrationImportFailed):
        resolve_migration_staging_path(storage, "/etc/passwd")


@pytest.mark.django_db
def test_import_rejects_inline_base64_and_client_pending_version(
    migrator: User,
    project_template_version,
) -> None:
    """Import must not accept Base64 or client-supplied pending_version_public_id."""

    del project_template_version
    staged = _stage_history_file(migrator.organization)
    with pytest.raises(MigrationImportFailed):
        ImportProjectMigrationBatch(
            context=CommandContext.for_actor(migrator),
            batch_key="batch-reject-b64",
            rows=[
                _d3_row(
                    migrator.organization,
                    external_id="EXT-B64",
                    history_files=[
                        {
                            "filename": "d2-report.pdf",
                            "mime_type": "application/pdf",
                            "content_base64": "AAAA",
                        }
                    ],
                )
            ],
        ).execute()
    with pytest.raises(MigrationImportFailed):
        ImportProjectMigrationBatch(
            context=CommandContext.for_actor(migrator),
            batch_key="batch-reject-pending",
            rows=[
                _d3_row(
                    migrator.organization,
                    external_id="EXT-PENDING",
                    history_files=[
                        {
                            **_history_file_entry(staged),
                            "pending_version_public_id": "00000000-0000-0000-0000-000000000099",
                        }
                    ],
                )
            ],
        ).execute()


@pytest.mark.django_db
def test_import_stages_history_files_without_storing_base64(
    migrator: User,
    project_template_version,
) -> None:
    """Import must reference streamed staging paths and never persist Base64 in MySQL."""

    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-strip",
        rows=[_d3_row(migrator.organization, external_id="EXT-STRIP")],
    ).execute()
    baseline = imported.baselines[0]
    assert "content_base64" not in baseline.history_files[0]
    assert "pending_version_public_id" not in baseline.history_files[0]
    assert baseline.history_files[0]["filename"] == "d2-report.pdf"
    assert baseline.history_files[0]["sha256"] == HISTORY_FILE_SHA256
    assert baseline.history_files[0]["size_bytes"] == len(HISTORY_FILE_BYTES)
    staging = baseline.history_files[0]["staging_relpath"]

    staged_path = get_file_storage().temp_dir() / staging
    assert staged_path.is_file()
    assert staged_path.read_bytes() == HISTORY_FILE_BYTES

    ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.CONTINUE,
        idempotency_key="confirm-strip",
    ).execute()

    baseline.refresh_from_db()
    assert baseline.history_files
    assert "content_base64" not in baseline.history_files[0]
    assert "staging_relpath" not in baseline.history_files[0]
    assert baseline.history_files[0]["filename"] == "d2-report.pdf"


@pytest.mark.django_db
def test_confirm_rollback_leaves_no_orphaned_storage_object(
    migrator: User,
    project_template_version,
    monkeypatch,
) -> None:
    """A database failure after staging must not leave an orphaned formal file.

    File activation is deferred until the confirm transaction commits, so a
    failure inside the transaction rolls back the file rows and never performs
    the physical storage move.
    """

    del project_template_version
    from apps.documents.models import DocumentSource, FileObject
    from apps.documents.storage.factory import get_file_storage

    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-rollback",
        rows=[_d3_row(migrator.organization, external_id="EXT-ROLLBACK")],
    ).execute()

    def _boom(**_kwargs: object) -> None:
        raise RuntimeError("simulated downstream DB failure")

    monkeypatch.setattr(
        "apps.projects.services.confirm_migration_baseline.materialize_template_tasks",
        _boom,
    )

    with pytest.raises(RuntimeError):
        ConfirmMigrationBaseline(
            context=CommandContext.for_actor(migrator),
            baseline_public_id=imported.baselines[0].public_id,
            disposition=MigrationDisposition.CONTINUE,
            idempotency_key="confirm-rollback",
        ).execute()

    # The staged file object rows rolled back with the transaction ...
    assert not FileObject.objects.filter(
        versions__document__source=DocumentSource.MIGRATION
    ).exists()
    # ... and no physical object was moved into permanent storage (the temp
    # staging payload may remain and is later swept by ReconcileStorage).
    objects_dir = get_file_storage().final_path_for("placeholder").parent
    orphans = [p for p in objects_dir.rglob("*") if p.is_file()] if objects_dir.exists() else []
    assert orphans == []


@pytest.mark.django_db
def test_confirm_idempotency_key_is_organization_scoped(
    migrator: User,
    grant_action: Callable[..., None],
    project_template_version,
) -> None:
    """The same confirm key may be reused by a different organization without conflict."""

    del project_template_version

    other_org = Organization.objects.create(name="Other Migration Org")
    other_director = User.objects.create_user(
        organization=other_org,
        display_name="Other Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(
        other_director,
        "project_migration.confirm",
        "project",
        role_code="PRODUCT_DIRECTOR",
    )

    # ARCHIVE_ONLY exercises the confirm idempotency key without needing a
    # published template in the second organization.
    shared_key = "shared-confirm-key"
    first = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="org-a-batch",
        rows=[_d3_row(migrator.organization, external_id="EXT-ORG-A")],
    ).execute()
    ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=first.baselines[0].public_id,
        disposition=MigrationDisposition.ARCHIVE_ONLY,
        idempotency_key=shared_key,
    ).execute()

    second = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(other_director),
        batch_key="org-b-batch",
        rows=[_d3_row(other_org, external_id="EXT-ORG-B")],
    ).execute()
    other_result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(other_director),
        baseline_public_id=second.baselines[0].public_id,
        disposition=MigrationDisposition.ARCHIVE_ONLY,
        idempotency_key=shared_key,
    ).execute()
    assert other_result.baseline.confirm_idempotency_key == shared_key
    assert other_result.baseline.organization_id == other_org.id


@pytest.mark.django_db
def test_archive_only_creates_no_project_or_todos(
    migrator: User,
    project_template_version,
) -> None:
    del project_template_version
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-archive",
        rows=[_d3_row(migrator.organization, external_id="EXT-ARC-1")],
    ).execute()
    baseline = imported.baselines[0]
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.ARCHIVE_ONLY,
        idempotency_key="confirm-arc",
    ).execute()
    assert result.project is None
    baseline.refresh_from_db()
    assert baseline.disposition == MigrationDisposition.ARCHIVE_ONLY
    assert Project.objects.filter(migration_baseline=baseline).count() == 0
    assert (
        Todo.objects.filter(
            organization=migrator.organization,
            title__icontains="EXT-ARC-1",
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_confirm_requires_permission(
    organization,
    grant_action: Callable[..., None],
    project_template_version,
) -> None:
    del project_template_version
    actor = User.objects.create_user(
        organization=organization,
        display_name="No Grant",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    director = User.objects.create_user(
        organization=organization,
        display_name="Import Director",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    grant_action(director, "project_migration.confirm", "project", role_code="PRODUCT_DIRECTOR")
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(director),
        batch_key="batch-deny",
        rows=[_d3_row(director.organization, external_id="EXT-DENY")],
    ).execute()
    with pytest.raises(PermissionDeniedError):
        ConfirmMigrationBaseline(
            context=CommandContext.for_actor(actor),
            baseline_public_id=imported.baselines[0].public_id,
            disposition=MigrationDisposition.CONTINUE,
            idempotency_key="deny-confirm",
        ).execute()


@pytest.mark.django_db
def test_pending_version_recovery_uses_staging_when_formal_missing(
    migrator: User,
    project_template_version,
) -> None:
    """Crash after remembering pending_version must still resume from staging bytes."""

    del project_template_version
    from apps.documents.models import DocumentSource, DocumentVersion, StorageStatus
    from apps.documents.services.ingest import stage_controlled_content
    from apps.projects.services.migration_activation import activate_or_recover_history_file

    staged = _stage_history_file(migrator.organization)
    storage = get_file_storage()
    temp_path = storage.temp_dir() / staged["staging_relpath"]
    version, pending = stage_controlled_content(
        organization=migrator.organization,
        source_temp_path=temp_path,
        sha256=staged["sha256"],
        size_bytes=staged["size_bytes"],
        original_filename=staged["filename"],
        mime_type=staged["mime_type"],
        uploaded_by=migrator,
        source=DocumentSource.MIGRATION,
    )
    assert version.file_object.storage_status == StorageStatus.PENDING
    assert not storage.final_path_for(pending.object_key).exists()
    assert temp_path.is_file()

    item = {
        **_history_file_entry(staged),
        "pending_version_public_id": str(version.public_id),
    }
    activated = activate_or_recover_history_file(
        item,
        organization_id=migrator.organization_id,
        storage=storage,
    )
    assert activated is not None
    activated.file_object.refresh_from_db()
    assert activated.file_object.storage_status == StorageStatus.ACTIVE
    assert DocumentVersion.objects.filter(public_id=version.public_id).count() == 1


@pytest.mark.django_db
def test_remember_pending_version_binds_by_staging_relpath_not_first_empty_code() -> None:
    """Multiple files without deliverable_code must not share one pending version id."""

    from apps.projects.services.confirm_migration_baseline import _remember_pending_version

    items = [
        {
            "filename": "a.pdf",
            "staging_relpath": "migration/aaa.part",
            "sha256": "a" * 64,
        },
        {
            "filename": "b.pdf",
            "staging_relpath": "migration/bbb.part",
            "sha256": "b" * 64,
        },
    ]
    updated = _remember_pending_version(
        items,
        deliverable_code="MIG-FILE-aaa",
        staging_relpath="migration/aaa.part",
        version_public_id="11111111-1111-1111-1111-111111111111",
    )
    assert updated[0]["pending_version_public_id"] == "11111111-1111-1111-1111-111111111111"
    assert "pending_version_public_id" not in updated[1]
