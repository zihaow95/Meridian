"""Uploads are governed by the published technical file catalog."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import TECHNICAL_FILE_CATALOG_CODE
from apps.documents.models import DocumentVersion, StorageStatus, VersionStatus
from apps.documents.services.catalog import (
    CatalogItemUnavailable,
    read_catalog_item,
    resolve_catalog_item,
)
from apps.documents.services.uploads import (
    CompleteUpload,
    CreateUploadSession,
    UploadValidationFailed,
)
from apps.documents.storage.base import StorageMoveFailed
from apps.identity.models.organization import Organization
from apps.identity.models.user import User

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.4 sample"


def catalog_item(**overrides: object) -> dict:
    item = {
        "item_code": "PRODUCT_SPEC",
        "name": "产品规格书",
        "allowed_mime_types": ["application/pdf"],
        "max_bytes": 52_428_800,
        "preview_enabled": True,
        "default_sensitivity_level": "PROJECT_CONTROLLED",
        "retention_years": 10,
    }
    item.update(overrides)
    return item


@pytest.fixture
def catalog_definition(organization: Organization) -> ConfigurationDefinition:
    return ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=TECHNICAL_FILE_CATALOG_CODE,
        name="Technical file catalog",
    )


@pytest.fixture
def publish_catalog(catalog_definition: ConfigurationDefinition, active_user: User):
    """Publish a catalog version without replaying the dual-control workflow."""

    def _publish(*items: dict, status: str = ConfigurationStatus.PUBLISHED) -> ConfigurationVersion:
        published = status == ConfigurationStatus.PUBLISHED
        if published:
            # Only one version may hold the slot; retire whoever holds it now.
            ConfigurationVersion.objects.filter(
                definition=catalog_definition, current_published_slot=1
            ).update(current_published_slot=None, status=ConfigurationStatus.RETIRED)
        last = (
            ConfigurationVersion.objects.filter(definition=catalog_definition)
            .order_by("-version_number")
            .first()
        )
        return ConfigurationVersion.objects.create(
            organization=catalog_definition.organization,
            definition=catalog_definition,
            version_number=1 if last is None else last.version_number + 1,
            status=status,
            content_json={"catalog_items": list(items)},
            current_published_slot=1 if published else None,
            created_by=active_user,
        )

    return _publish


@pytest.fixture
def catalogued_session(active_user: User, file_storage):
    """Start a catalogued upload session and put bytes in its temp path."""

    def _start(
        *,
        item_code: str = "PRODUCT_SPEC",
        mime: str = "application/pdf",
        content: bytes = PDF_BYTES,
    ):
        session = CreateUploadSession(
            actor=active_user,
            original_filename="spec.pdf",
            declared_mime_type=mime,
            storage=file_storage,
            catalog_item_code=item_code,
        ).execute()
        path = Path(session.temp_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        session.size_bytes = len(content)
        session.sha256 = hashlib.sha256(content).hexdigest()
        session.save(update_fields=["size_bytes", "sha256"])
        return session

    return _start


def test_resolves_the_rules_of_an_item_in_the_published_catalog(
    organization: Organization, publish_catalog
) -> None:
    publish_catalog(catalog_item())

    rules = resolve_catalog_item(organization=organization, item_code="PRODUCT_SPEC")

    assert rules.name == "产品规格书"
    assert rules.allowed_mime_types == frozenset({"application/pdf"})
    assert rules.max_bytes == 52_428_800
    assert rules.preview_enabled is True
    assert rules.default_sensitivity_level == "PROJECT_CONTROLLED"
    assert rules.retention_years == 10


def test_an_item_the_catalog_does_not_list_cannot_be_uploaded(
    organization: Organization, publish_catalog
) -> None:
    publish_catalog(catalog_item())

    with pytest.raises(CatalogItemUnavailable):
        resolve_catalog_item(organization=organization, item_code="NOT_IN_CATALOG")


def test_a_disabled_item_cannot_be_uploaded(organization: Organization, publish_catalog) -> None:
    publish_catalog(catalog_item(enabled=False))

    with pytest.raises(CatalogItemUnavailable):
        resolve_catalog_item(organization=organization, item_code="PRODUCT_SPEC")


def test_an_item_without_an_enabled_flag_is_usable(
    organization: Organization, publish_catalog
) -> None:
    publish_catalog(catalog_item())

    assert resolve_catalog_item(organization=organization, item_code="PRODUCT_SPEC")


def test_uploads_are_refused_when_no_catalog_is_published_yet(
    organization: Organization, catalog_definition: ConfigurationDefinition
) -> None:
    with pytest.raises(CatalogItemUnavailable):
        resolve_catalog_item(organization=organization, item_code="PRODUCT_SPEC")


def test_a_draft_catalog_does_not_govern_uploads(
    organization: Organization, publish_catalog
) -> None:
    publish_catalog(catalog_item(), status=ConfigurationStatus.DRAFT)

    with pytest.raises(CatalogItemUnavailable):
        resolve_catalog_item(organization=organization, item_code="PRODUCT_SPEC")


def test_the_code_level_safety_cap_overrides_an_oversized_configured_limit(
    organization: Organization, publish_catalog, settings
) -> None:
    settings.DOCUMENT_UPLOAD_HARD_MAX_BYTES = 104_857_600
    publish_catalog(catalog_item(max_bytes=10_737_418_240))

    rules = resolve_catalog_item(organization=organization, item_code="PRODUCT_SPEC")

    assert rules.max_bytes == 104_857_600


def test_rules_carry_the_catalog_version_and_digest_so_a_session_can_lock_them(
    organization: Organization, publish_catalog
) -> None:
    version = publish_catalog(catalog_item())

    rules = resolve_catalog_item(organization=organization, item_code="PRODUCT_SPEC")

    assert rules.catalog_version_public_id == version.public_id
    assert rules.catalog_content_digest == version.content_digest


def test_a_locked_session_keeps_reading_the_catalog_version_it_started_with(
    organization: Organization, publish_catalog
) -> None:
    started_with = publish_catalog(catalog_item(max_bytes=1_048_576))
    publish_catalog(catalog_item(max_bytes=52_428_800))

    rules = read_catalog_item(catalog_version=started_with, item_code="PRODUCT_SPEC")

    assert rules.max_bytes == 1_048_576


def test_a_session_records_the_catalog_version_and_digest_it_started_under(
    publish_catalog, catalogued_session
) -> None:
    catalog = publish_catalog(catalog_item())

    session = catalogued_session()

    assert session.catalog_item_code == "PRODUCT_SPEC"
    assert session.catalog_version_public_id == catalog.public_id
    assert session.catalog_content_digest == catalog.content_digest


def test_a_session_cannot_start_for_an_item_the_catalog_does_not_list(
    publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item())

    with pytest.raises(CatalogItemUnavailable):
        catalogued_session(item_code="NOT_IN_CATALOG")


def test_a_session_cannot_start_with_a_mime_type_the_item_forbids(
    publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item(allowed_mime_types=["image/png"]))

    with pytest.raises(UploadValidationFailed):
        catalogued_session()


def test_republishing_the_catalog_does_not_change_the_rules_of_a_started_session(
    active_user: User, file_storage, publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item(max_bytes=1_048_576))
    session = catalogued_session()
    # The item is withdrawn while the upload is in flight.
    publish_catalog(catalog_item(enabled=False))

    version = CompleteUpload(
        session_public_id=session.public_id, actor=active_user, storage=file_storage
    ).execute()

    assert version.status == VersionStatus.CONTROLLED


def test_a_file_over_the_item_limit_is_refused_on_completion(
    active_user: User, file_storage, publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item(max_bytes=8))
    session = catalogued_session()

    with pytest.raises(UploadValidationFailed):
        CompleteUpload(
            session_public_id=session.public_id, actor=active_user, storage=file_storage
        ).execute()


def test_an_empty_file_is_refused_on_completion(
    active_user: User, file_storage, publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item())
    session = catalogued_session(content=b"")

    with pytest.raises(UploadValidationFailed):
        CompleteUpload(
            session_public_id=session.public_id, actor=active_user, storage=file_storage
        ).execute()


def test_bytes_that_contradict_the_declared_mime_type_are_refused(
    active_user: User, file_storage, publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item())
    session = catalogued_session(content=b"\x89PNG\r\n\x1a\nnot a pdf")

    with pytest.raises(UploadValidationFailed):
        CompleteUpload(
            session_public_id=session.public_id, actor=active_user, storage=file_storage
        ).execute()


def test_a_failed_move_leaves_no_referencable_controlled_version(
    active_user: User, storage_that_fails_move, publish_catalog, file_storage, catalogued_session
) -> None:
    publish_catalog(catalog_item())
    session = catalogued_session()

    with pytest.raises(StorageMoveFailed):
        CompleteUpload(
            session_public_id=session.public_id,
            actor=active_user,
            storage=storage_that_fails_move,
        ).execute()

    session.refresh_from_db()
    assert session.completed_at is None
    version = session.document_version
    assert version is not None
    assert version.status == VersionStatus.DRAFT
    assert version.file_object.storage_status == StorageStatus.PENDING


def test_completing_the_same_session_twice_is_refused(
    active_user: User, file_storage, publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item())
    session = catalogued_session()
    CompleteUpload(
        session_public_id=session.public_id, actor=active_user, storage=file_storage
    ).execute()

    with pytest.raises(UploadValidationFailed):
        CompleteUpload(
            session_public_id=session.public_id, actor=active_user, storage=file_storage
        ).execute()


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_completions_settle_to_one_controlled_version(
    active_user: User, file_storage, publish_catalog, catalogued_session
) -> None:
    """Catalog validation must not open a second path to a duplicate version."""

    import threading

    from django.db import connection

    publish_catalog(catalog_item())
    session = catalogued_session()

    results: list[str] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def _complete(label: str) -> None:
        connection.close()
        try:
            barrier.wait(timeout=5)
            CompleteUpload(
                session_public_id=session.public_id, actor=active_user, storage=file_storage
            ).execute()
            with lock:
                results.append(f"ok:{label}")
        except UploadValidationFailed:
            with lock:
                results.append(f"done:{label}")
        except Exception as exc:  # noqa: BLE001 - collect for assert
            with lock:
                results.append(f"error:{type(exc).__name__}:{label}")
        finally:
            connection.close()

    threads = [
        threading.Thread(target=_complete, args=("a",)),
        threading.Thread(target=_complete, args=("b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "concurrent catalogued complete did not finish"

    assert not any(item.startswith("error:") for item in results)
    assert any(item.startswith("ok:") for item in results)
    assert DocumentVersion.objects.filter(status=VersionStatus.CONTROLLED).count() == 1


def test_the_upload_api_refuses_a_catalog_item_that_is_not_published(
    client, active_user: User, grant_action, publish_catalog
) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    publish_catalog(catalog_item())
    grant_action(active_user, "document.version.upload", "document.version")
    client.force_login(active_user)

    response = client.post(
        "/api/v1/documents/uploads",
        data={
            "file": SimpleUploadedFile("spec.pdf", PDF_BYTES, content_type="application/pdf"),
            "declared_mime_type": "application/pdf",
            "catalog_item_code": "NOT_IN_CATALOG",
        },
    )

    assert response.status_code == 400


def test_the_upload_api_records_the_catalog_item_on_the_session(
    client, active_user: User, grant_action, publish_catalog
) -> None:
    from django.core.files.uploadedfile import SimpleUploadedFile

    publish_catalog(catalog_item())
    grant_action(active_user, "document.version.upload", "document.version")
    client.force_login(active_user)

    response = client.post(
        "/api/v1/documents/uploads",
        data={
            "file": SimpleUploadedFile("spec.pdf", PDF_BYTES, content_type="application/pdf"),
            "declared_mime_type": "application/pdf",
            "catalog_item_code": "PRODUCT_SPEC",
        },
    )

    assert response.status_code == 201
    assert response.json()["catalog_item_code"] == "PRODUCT_SPEC"


def test_the_controlled_version_carries_the_catalog_item_and_its_sensitivity(
    active_user: User, file_storage, publish_catalog, catalogued_session
) -> None:
    publish_catalog(catalog_item(default_sensitivity_level="SENSITIVE_CONTROLLED"))
    session = catalogued_session()

    version = CompleteUpload(
        session_public_id=session.public_id, actor=active_user, storage=file_storage
    ).execute()

    assert version.catalog_item_code == "PRODUCT_SPEC"
    assert version.sensitivity_level == "SENSITIVE_CONTROLLED"
