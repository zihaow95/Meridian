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
    uploaded_by: User,
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
        uploaded_by=uploaded_by,
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
    uploaded_by: User,
    *,
    external_id: str = "EXT-D3-001",
    history_files: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if history_files is None:
        history_files = [_history_file_entry(_stage_history_file(organization, uploaded_by))]
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
        rows=[_d3_row(migrator.organization, migrator)],
    ).execute()
    second = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-1",
        rows=[_d3_row(migrator.organization, migrator)],
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
        rows=[_d3_row(migrator.organization, migrator)],
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
        rows=[_d3_row(migrator.organization, migrator)],
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
    row = _d3_row(migrator.organization, migrator, external_id="EXT-NOFILE", history_files=[])
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
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-DOWNLOAD")],
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
    assert migrated["can_download"] is False

    # Without the download right, the ticket request is denied.
    denied = api_client.post(f"/api/v1/documents/versions/{version_public_id}/download-ticket")
    assert denied.status_code in (403, 404)

    # With the download right, list capability flips and a ticket is issued.
    grant_action(migrator, "document.version.download", "document.version")
    listing_allowed = api_client.get(f"/api/v1/projects/{project.public_id}/deliverables")
    assert listing_allowed.status_code == 200
    migrated_allowed = next(
        row for row in listing_allowed.json()["items"] if row["name"] == "d2-report.pdf"
    )
    assert migrated_allowed["can_download"] is True
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
    staged = _stage_history_file(migrator.organization, migrator)
    with pytest.raises(MigrationImportFailed):
        ImportProjectMigrationBatch(
            context=CommandContext.for_actor(migrator),
            batch_key="batch-reject-b64",
            rows=[
                _d3_row(
                    migrator.organization,
                    migrator,
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
                    migrator,
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
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-STRIP")],
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
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-ROLLBACK")],
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
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-ORG-A")],
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
        rows=[_d3_row(other_org, other_director, external_id="EXT-ORG-B")],
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
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-ARC-1")],
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
        rows=[_d3_row(director.organization, director, external_id="EXT-DENY")],
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

    staged = _stage_history_file(migrator.organization, migrator)
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


@pytest.mark.django_db
def test_migration_file_stage_api_allows_and_denies(
    migrator: User,
    organization,
    grant_action: Callable[..., None],
    api_client,
    project_template_version,
) -> None:
    """Stage endpoint requires project_migration.confirm; allowed actors get a durable handle."""

    del project_template_version
    from django.core.files.uploadedfile import SimpleUploadedFile

    from apps.audit.models import AuditEvent
    from apps.platform.outbox.models import OutboxEvent
    from apps.projects.models import MigrationFileStage

    stranger = User.objects.create_user(
        organization=organization,
        display_name="No Migration Right",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )
    api_client.force_authenticate(user=stranger)
    denied = api_client.post(
        "/api/v1/project-migration-files/stage",
        {
            "file": SimpleUploadedFile(
                "deny.pdf", HISTORY_FILE_BYTES, content_type="application/pdf"
            ),
            "filename": "deny.pdf",
            "mime_type": "application/pdf",
        },
        format="multipart",
    )
    assert denied.status_code in (403, 404)

    api_client.force_authenticate(user=migrator)
    allowed = api_client.post(
        "/api/v1/project-migration-files/stage",
        {
            "file": SimpleUploadedFile(
                "allow.pdf", HISTORY_FILE_BYTES, content_type="application/pdf"
            ),
            "filename": "allow.pdf",
            "mime_type": "application/pdf",
        },
        format="multipart",
    )
    assert allowed.status_code == 201
    body = allowed.json()
    assert body["staging_relpath"].startswith("migration/")
    assert body["sha256"] == HISTORY_FILE_SHA256
    stage = MigrationFileStage.objects.get(public_id=body["public_id"])
    assert stage.uploaded_by_id == migrator.id
    assert stage.organization_id == migrator.organization_id
    assert stage.claimed_at is None
    assert AuditEvent.objects.filter(
        action_code="project_migration.confirm",
        resource_public_id=stage.public_id,
    ).exists()
    assert OutboxEvent.objects.filter(event_type="project_migration.file_staged").exists()
    del grant_action


@pytest.mark.django_db
def test_staging_handle_is_single_claim(
    migrator: User,
    project_template_version,
) -> None:
    """The same staging_relpath cannot be imported into two baselines."""

    del project_template_version
    staged = _stage_history_file(migrator.organization, migrator)
    entry = _history_file_entry(staged)
    ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-claim-a",
        rows=[
            _d3_row(
                migrator.organization,
                migrator,
                external_id="EXT-CLAIM-A",
                history_files=[entry],
            )
        ],
    ).execute()
    with pytest.raises(MigrationImportFailed):
        ImportProjectMigrationBatch(
            context=CommandContext.for_actor(migrator),
            batch_key="batch-claim-b",
            rows=[
                _d3_row(
                    migrator.organization,
                    migrator,
                    external_id="EXT-CLAIM-B",
                    history_files=[entry],
                )
            ],
        ).execute()


@pytest.mark.django_db
def test_duplicate_staging_relpath_within_one_baseline_is_rejected(
    migrator: User,
    project_template_version,
) -> None:
    """One baseline must not reference the same staging handle twice."""

    del project_template_version
    staged = _stage_history_file(migrator.organization, migrator)
    entry = _history_file_entry(staged)
    with pytest.raises(MigrationImportFailed):
        ImportProjectMigrationBatch(
            context=CommandContext.for_actor(migrator),
            batch_key="batch-dup-handle",
            rows=[
                _d3_row(
                    migrator.organization,
                    migrator,
                    external_id="EXT-DUP",
                    history_files=[entry, dict(entry)],
                )
            ],
        ).execute()
    assert MigrationBaseline.objects.filter(external_project_id="EXT-DUP").count() == 0


@pytest.mark.django_db(transaction=True)
def test_stage_command_rolls_back_when_audit_write_fails(
    migrator: User,
    project_template_version,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit failure must not leave a MigrationFileStage row or temp part."""

    del project_template_version
    from apps.audit.services.append_event import AuditWriteFailed
    from apps.documents.storage.factory import get_file_storage
    from apps.projects.models import MigrationFileStage
    from apps.projects.services.stage_migration_file import StageMigrationFile

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AuditWriteFailed("audit insert failed")

    monkeypatch.setattr(
        "apps.projects.services.stage_migration_file.append_event",
        _boom,
    )
    storage = get_file_storage()
    with pytest.raises(AuditWriteFailed):
        StageMigrationFile(
            context=CommandContext.for_actor(migrator),
            chunks=iter([HISTORY_FILE_BYTES]),
            filename="rollback.pdf",
            mime_type="application/pdf",
            storage=storage,
        ).execute()
    assert MigrationFileStage.objects.count() == 0
    migration_dir = storage.temp_dir() / "migration"
    leftovers = list(migration_dir.glob("*.part")) if migration_dir.exists() else []
    assert leftovers == []


@pytest.mark.django_db
def test_archive_only_activates_and_consumes_history_files(
    migrator: User,
    project_template_version,
) -> None:
    """ARCHIVE_ONLY must create formal DocumentVersions and consume staging handles."""

    del project_template_version
    from apps.documents.models import DocumentVersion, VersionStatus
    from apps.projects.models import MigrationFileStage

    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-archive-files",
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-ARC-FILE")],
    ).execute()
    baseline = imported.baselines[0]
    staging = baseline.history_files[0]["staging_relpath"]
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.ARCHIVE_ONLY,
        idempotency_key="confirm-arc-files",
    ).execute()
    assert result.project is None
    baseline.refresh_from_db()
    assert "staging_relpath" not in baseline.history_files[0]
    version_id = baseline.history_files[0]["document_version_public_id"]
    assert version_id
    version = DocumentVersion.objects.get(public_id=version_id)
    assert version.status == VersionStatus.CONTROLLED
    stage = MigrationFileStage.objects.get(staging_relpath=staging)
    assert stage.consumed_at is not None


@pytest.mark.django_db
def test_archive_only_activate_failure_retries_with_same_idempotency_key(
    migrator: User,
    project_template_version,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ARCHIVE_ONLY activate failure must recover on same-key retry (no stuck CONFIRMED)."""

    del project_template_version
    from apps.documents.models import DocumentVersion, VersionStatus
    from apps.projects.models import MigrationBaselineStatus, MigrationFileStage

    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-archive-retry",
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-ARC-RETRY")],
    ).execute()
    baseline = imported.baselines[0]
    staging = baseline.history_files[0]["staging_relpath"]
    idempotency_key = "confirm-arc-retry"

    def _boom(self: object, **_kwargs: object) -> MigrationBaseline:
        del self
        raise MigrationImportFailed(message="simulated archive activate failure")

    monkeypatch.setattr(
        ConfirmMigrationBaseline,
        "_activate_archived_history_files",
        _boom,
    )
    with pytest.raises(MigrationImportFailed, match="simulated archive activate failure"):
        ConfirmMigrationBaseline(
            context=CommandContext.for_actor(migrator),
            baseline_public_id=baseline.public_id,
            disposition=MigrationDisposition.ARCHIVE_ONLY,
            idempotency_key=idempotency_key,
        ).execute()

    baseline.refresh_from_db()
    assert baseline.status == MigrationBaselineStatus.CONFIRMED
    assert baseline.history_files[0].get("staging_relpath") == staging
    stage = MigrationFileStage.objects.get(staging_relpath=staging)
    assert stage.consumed_at is None

    monkeypatch.undo()
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.ARCHIVE_ONLY,
        idempotency_key=idempotency_key,
    ).execute()
    assert result.project is None
    baseline.refresh_from_db()
    assert "staging_relpath" not in baseline.history_files[0]
    version_id = baseline.history_files[0]["document_version_public_id"]
    assert version_id
    version = DocumentVersion.objects.get(public_id=version_id)
    assert version.status == VersionStatus.CONTROLLED
    stage.refresh_from_db()
    assert stage.consumed_at is not None


@pytest.mark.django_db
def test_archive_only_mid_file_activate_failure_consumes_success_and_retries(
    migrator: User,
    project_template_version,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First file ACTIVE + second fail must consume the success stage; retry finishes both."""

    del project_template_version
    from apps.documents.models import DocumentVersion, VersionStatus
    from apps.documents.services.ingest import ControlledIngestFailed
    from apps.projects.models import MigrationFileStage
    from apps.projects.services import confirm_migration_baseline as confirm_mod

    first = _stage_history_file(
        migrator.organization, migrator, filename="arc-a.pdf", content=b"%PDF-1.4 a"
    )
    second = _stage_history_file(
        migrator.organization, migrator, filename="arc-b.pdf", content=b"%PDF-1.4 b"
    )
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-archive-midfail",
        rows=[
            _d3_row(
                migrator.organization,
                migrator,
                external_id="EXT-ARC-MID",
                history_files=[
                    _history_file_entry(first),
                    _history_file_entry(second),
                ],
            )
        ],
    ).execute()
    baseline = imported.baselines[0]
    staging_a = baseline.history_files[0]["staging_relpath"]
    staging_b = baseline.history_files[1]["staging_relpath"]
    idempotency_key = "confirm-arc-midfail"

    original = confirm_mod.activate_or_recover_history_file
    calls = {"n": 0}

    def _fail_second(item: dict[str, Any], **kwargs: Any) -> DocumentVersion | None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ControlledIngestFailed("simulated mid-file activate failure")
        return original(item, **kwargs)

    monkeypatch.setattr(confirm_mod, "activate_or_recover_history_file", _fail_second)
    with pytest.raises(ControlledIngestFailed, match="simulated mid-file activate failure"):
        ConfirmMigrationBaseline(
            context=CommandContext.for_actor(migrator),
            baseline_public_id=baseline.public_id,
            disposition=MigrationDisposition.ARCHIVE_ONLY,
            idempotency_key=idempotency_key,
        ).execute()

    baseline.refresh_from_db()
    assert baseline.history_files[0].get("document_version_public_id")
    assert baseline.history_files[0].get("staging_relpath") == staging_a
    assert baseline.history_files[1].get("pending_version_public_id")
    assert not baseline.history_files[1].get("document_version_public_id")
    stage_a = MigrationFileStage.objects.get(staging_relpath=staging_a)
    stage_b = MigrationFileStage.objects.get(staging_relpath=staging_b)
    assert stage_a.consumed_at is not None
    assert stage_b.consumed_at is None

    monkeypatch.undo()
    result = ConfirmMigrationBaseline(
        context=CommandContext.for_actor(migrator),
        baseline_public_id=baseline.public_id,
        disposition=MigrationDisposition.ARCHIVE_ONLY,
        idempotency_key=idempotency_key,
    ).execute()
    assert result.project is None
    baseline.refresh_from_db()
    assert "staging_relpath" not in baseline.history_files[0]
    assert "staging_relpath" not in baseline.history_files[1]
    for row in baseline.history_files:
        version = DocumentVersion.objects.get(public_id=row["document_version_public_id"])
        assert version.status == VersionStatus.CONTROLLED
    stage_a.refresh_from_db()
    stage_b.refresh_from_db()
    assert stage_a.consumed_at is not None
    assert stage_b.consumed_at is not None


@pytest.mark.django_db
def test_archive_only_pending_stage_failure_rolls_back_orphans(
    migrator: User,
    project_template_version,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PENDING staging must be one transaction: later stage failure leaves no orphan rows."""

    del project_template_version
    from apps.documents.models import DocumentVersion, FileObject
    from apps.documents.services.ingest import ControlledIngestFailed, stage_controlled_content

    first = _stage_history_file(
        migrator.organization, migrator, filename="pend-a.pdf", content=b"%PDF-1.4 pa"
    )
    second = _stage_history_file(
        migrator.organization, migrator, filename="pend-b.pdf", content=b"%PDF-1.4 pb"
    )
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-archive-pend-txn",
        rows=[
            _d3_row(
                migrator.organization,
                migrator,
                external_id="EXT-ARC-PEND",
                history_files=[
                    _history_file_entry(first),
                    _history_file_entry(second),
                ],
            )
        ],
    ).execute()
    baseline = imported.baselines[0]
    before_files = FileObject.objects.count()
    before_versions = DocumentVersion.objects.count()

    original = stage_controlled_content
    calls = {"n": 0}

    def _fail_second(**kwargs: Any) -> tuple[Any, Any]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ControlledIngestFailed("simulated pending stage failure")
        return original(**kwargs)

    monkeypatch.setattr(
        "apps.documents.services.ingest.stage_controlled_content",
        _fail_second,
    )
    with pytest.raises(ControlledIngestFailed, match="simulated pending stage failure"):
        ConfirmMigrationBaseline(
            context=CommandContext.for_actor(migrator),
            baseline_public_id=baseline.public_id,
            disposition=MigrationDisposition.ARCHIVE_ONLY,
            idempotency_key="confirm-arc-pend-txn",
        ).execute()

    baseline.refresh_from_db()
    assert not baseline.history_files[0].get("pending_version_public_id")
    assert not baseline.history_files[1].get("pending_version_public_id")
    assert FileObject.objects.count() == before_files
    assert DocumentVersion.objects.count() == before_versions


@pytest.mark.django_db(transaction=True)
def test_archive_only_same_key_concurrent_confirm_leaves_one_file_fact(
    migrator: User,
    project_template_version,
) -> None:
    """Two same-key ARCHIVE_ONLY confirms must leave one Document/Version/FileObject set."""

    del project_template_version
    import threading

    from django.db import connection

    from apps.documents.models import Document, DocumentSource, DocumentVersion, VersionStatus
    from apps.projects.models import MigrationFileStage

    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-archive-concurrent",
        rows=[_d3_row(migrator.organization, migrator, external_id="EXT-ARC-CONC")],
    ).execute()
    baseline = imported.baselines[0]
    staging = baseline.history_files[0]["staging_relpath"]
    idempotency_key = "confirm-arc-concurrent"
    baseline_public_id = baseline.public_id
    org_id = migrator.organization_id

    results: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def _confirm(label: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=10)
            ConfirmMigrationBaseline(
                context=CommandContext.for_actor(migrator),
                baseline_public_id=baseline_public_id,
                disposition=MigrationDisposition.ARCHIVE_ONLY,
                idempotency_key=idempotency_key,
            ).execute()
            with lock:
                results.append(f"ok:{label}")
        except Exception as exc:  # noqa: BLE001 - collect for assert
            with lock:
                results.append(f"error:{type(exc).__name__}:{label}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_confirm, args=("a",)),
        threading.Thread(target=_confirm, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "concurrent ARCHIVE_ONLY worker did not finish"

    assert len(results) == 2
    assert results.count("ok:a") + results.count("ok:b") == 2, results

    baseline.refresh_from_db()
    assert len(baseline.history_files) == 1
    version_id = baseline.history_files[0]["document_version_public_id"]
    assert version_id
    assert "staging_relpath" not in baseline.history_files[0]

    migration_docs = Document.objects.filter(
        organization_id=org_id,
        source=DocumentSource.MIGRATION,
        category="MIGRATION_ARCHIVE",
    )
    assert migration_docs.count() == 1
    versions = DocumentVersion.objects.filter(document__in=migration_docs)
    assert versions.count() == 1
    version = versions.get()
    assert str(version.public_id) == str(version_id)
    assert version.status == VersionStatus.CONTROLLED
    assert version.file_object_id is not None
    from apps.documents.models import FileObject, StorageStatus

    assert (
        FileObject.objects.filter(
            id=version.file_object_id,
            organization_id=org_id,
            storage_status=StorageStatus.ACTIVE,
        ).count()
        == 1
    )
    # No orphan migration-archive FileObjects beyond the single baseline fact.
    assert (
        FileObject.objects.filter(
            organization_id=org_id,
            versions__document__source=DocumentSource.MIGRATION,
            versions__document__category="MIGRATION_ARCHIVE",
        )
        .distinct()
        .count()
        == 1
    )

    stage = MigrationFileStage.objects.get(staging_relpath=staging)
    assert stage.consumed_at is not None
    assert stage.claimed_baseline_id == baseline.id


@pytest.mark.django_db
def test_cross_list_duplicate_handle_rolls_back_while_sibling_row_succeeds(
    migrator: User,
    project_template_version,
) -> None:
    """Cross-list duplicate handle must not leave a baseline when a sibling succeeds."""

    del project_template_version
    from apps.projects.models import MigrationFileStage

    staged = _stage_history_file(migrator.organization, migrator)
    entry = _history_file_entry(staged)
    good_row = _d3_row(migrator.organization, migrator, external_id="EXT-SIB-GOOD")
    bad_row = {
        "external_project_id": "EXT-SIB-BAD",
        "name": "Cross-list duplicate",
        "current_stage_code": "D3",
        "leader_display_name": "Legacy Leader",
        "disposition": MigrationDisposition.CONTINUE,
        "history_decision_summary": "bad row",
        "plan_summary": {},
        "history_tasks": [],
        "history_files": [entry],
        "history_deliverables": [dict(entry)],
    }
    imported = ImportProjectMigrationBatch(
        context=CommandContext.for_actor(migrator),
        batch_key="batch-cross-dup-sibling",
        rows=[bad_row, good_row],
    ).execute()
    assert imported.accepted_count == 1
    assert imported.error_count == 1
    assert MigrationBaseline.objects.filter(external_project_id="EXT-SIB-BAD").count() == 0
    assert MigrationBaseline.objects.filter(external_project_id="EXT-SIB-GOOD").count() == 1
    assert any(
        err.get("external_project_id") == "EXT-SIB-BAD"
        and "Duplicate staging_relpath" in str(err.get("error") or "")
        for err in imported.batch.row_errors
    )
    # Bad row must not leave a claim on the duplicated handle.
    bad_stage = MigrationFileStage.objects.get(staging_relpath=entry["staging_relpath"])
    assert bad_stage.claimed_baseline_id is None


@pytest.mark.django_db(transaction=True)
def test_stage_reauthorizes_inside_write_transaction(
    migrator: User,
    project_template_version,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Permission revoked after streaming must deny persist/audit/outbox."""

    del project_template_version
    from apps.authorization.models.assignment import RoleAssignment
    from apps.documents.storage.factory import get_file_storage
    from apps.projects.models import MigrationFileStage
    from apps.projects.services import stage_migration_file as stage_mod

    original_write = stage_mod.write_migration_staging_bytes

    def write_then_revoke(*args: object, **kwargs: object) -> tuple[str, object, str, int]:
        result = original_write(*args, **kwargs)
        RoleAssignment.objects.filter(user=migrator).delete()
        return result

    monkeypatch.setattr(stage_mod, "write_migration_staging_bytes", write_then_revoke)
    with pytest.raises(PermissionDeniedError):
        stage_mod.StageMigrationFile(
            context=CommandContext.for_actor(migrator),
            chunks=iter([HISTORY_FILE_BYTES]),
            filename="reauth.pdf",
            mime_type="application/pdf",
            storage=get_file_storage(),
        ).execute()
    assert MigrationFileStage.objects.count() == 0
