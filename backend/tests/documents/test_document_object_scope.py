"""Document version reads are scoped by object and by data sensitivity."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from django.test import Client
from django.utils import timezone

from apps.authorization.models.assignment import RoleAssignment, ScopeType, build_scope_key
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleType,
)
from apps.documents.models import DocumentSource, DocumentVersion
from apps.documents.services.ingest import activate_staged_content, stage_controlled_content
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus

pytestmark = pytest.mark.django_db

PDF_BYTES = b"%PDF-1.4 sample"


@pytest.fixture
def other_user(organization: Organization) -> User:
    return User.objects.create_user(
        organization=organization,
        display_name="Other User",
        status=UserStatus.ACTIVE,
        activated_at=timezone.now(),
    )


@pytest.fixture
def grant_download_up_to(db: None):
    """Grant document download capped at a specific data sensitivity level."""

    def _grant(user: User, max_data_level: str) -> None:
        action, _ = PermissionAction.objects.get_or_create(
            action_code="document.version.download",
            defaults={
                "resource_type": "document.version",
                "action_category": ActionCategory.READ,
            },
        )
        role, _ = Role.objects.get_or_create(
            role_code=f"ROLE_DOC_DOWNLOAD_{max_data_level}",
            defaults={"name": f"Doc download {max_data_level}", "role_type": RoleType.PLATFORM},
        )
        RolePermission.objects.get_or_create(
            role=role,
            action=action,
            defaults={"max_data_level": max_data_level, "requires_object_scope": False},
        )
        scope_key = build_scope_key(
            scope_type=ScopeType.ORGANIZATION, scope_id=user.organization_id
        )
        RoleAssignment.objects.get_or_create(
            user=user,
            role=role,
            scope_type=ScopeType.ORGANIZATION,
            scope_key=scope_key,
            defaults={
                "scope_id": user.organization_id,
                "effective_from": timezone.now(),
                "configured_by": user,
                "status": "ACTIVE",
                "active_slot": 1,
            },
        )

    return _grant


@pytest.fixture
def controlled_version(organization: Organization):
    # Use the runtime storage the API itself resolves, so a download served
    # through the view finds the same bytes this fixture activated.
    storage = get_file_storage()

    def _create(*, uploaded_by: User, sensitivity_level: str) -> DocumentVersion:
        temp_path = storage.temp_dir() / f"{sensitivity_level}.part"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(PDF_BYTES)
        _, staged = stage_controlled_content(
            organization=organization,
            source_temp_path=Path(temp_path),
            sha256=hashlib.sha256(PDF_BYTES).hexdigest(),
            size_bytes=len(PDF_BYTES),
            original_filename="spec.pdf",
            mime_type="application/pdf",
            uploaded_by=uploaded_by,
            source=DocumentSource.PRODUCT,
            sensitivity_level=sensitivity_level,
            catalog_item_code="PRODUCT_SPEC",
        )
        return activate_staged_content(staged, storage)

    return _create


def test_a_reader_cleared_only_for_internal_data_gets_no_ticket_for_a_sensitive_file(
    client: Client, active_user: User, other_user: User, controlled_version, grant_download_up_to
) -> None:
    version = controlled_version(
        uploaded_by=other_user, sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED
    )
    grant_download_up_to(active_user, DataSensitivityLevel.INTERNAL)
    client.force_login(active_user)

    response = client.post(f"/api/v1/documents/versions/{version.public_id}/download-ticket")

    assert response.status_code == 404


def test_a_reader_cleared_for_the_level_gets_a_ticket(
    client: Client, active_user: User, other_user: User, controlled_version, grant_download_up_to
) -> None:
    version = controlled_version(
        uploaded_by=other_user, sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED
    )
    grant_download_up_to(active_user, DataSensitivityLevel.SENSITIVE_CONTROLLED)
    client.force_login(active_user)

    response = client.post(f"/api/v1/documents/versions/{version.public_id}/download-ticket")

    assert response.status_code == 200
    assert response.json()["token"]


def test_uploading_a_file_does_not_by_itself_confer_the_right_to_download_it(
    client: Client, active_user: User, controlled_version
) -> None:
    version = controlled_version(
        uploaded_by=active_user, sensitivity_level=DataSensitivityLevel.INTERNAL
    )
    client.force_login(active_user)

    response = client.post(f"/api/v1/documents/versions/{version.public_id}/download-ticket")

    assert response.status_code == 404


def test_a_ticket_cannot_be_replayed_after_it_is_consumed(
    client: Client, active_user: User, controlled_version, grant_download_up_to
) -> None:
    version = controlled_version(
        uploaded_by=active_user, sensitivity_level=DataSensitivityLevel.INTERNAL
    )
    grant_download_up_to(active_user, DataSensitivityLevel.INTERNAL)
    client.force_login(active_user)
    token = client.post(f"/api/v1/documents/versions/{version.public_id}/download-ticket").json()[
        "token"
    ]

    assert client.get(f"/api/v1/documents/download/{token}").status_code == 200
    # Anyone replaying the same token, including another session, is refused.
    assert client.get(f"/api/v1/documents/download/{token}").status_code == 404


def test_the_version_list_hides_files_above_the_readers_clearance(
    client: Client, active_user: User, other_user: User, controlled_version, grant_download_up_to
) -> None:
    version = controlled_version(
        uploaded_by=other_user, sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE
    )
    grant_download_up_to(active_user, DataSensitivityLevel.INTERNAL)
    client.force_login(active_user)

    response = client.get(f"/api/v1/documents/{version.document.public_id}/versions")

    assert response.status_code == 200
    assert response.json() == []


def test_the_version_list_shows_files_at_or_below_the_readers_clearance(
    client: Client, active_user: User, other_user: User, controlled_version, grant_download_up_to
) -> None:
    version = controlled_version(
        uploaded_by=other_user, sensitivity_level=DataSensitivityLevel.INTERNAL
    )
    grant_download_up_to(active_user, DataSensitivityLevel.PROJECT_CONTROLLED)
    client.force_login(active_user)

    response = client.get(f"/api/v1/documents/{version.document.public_id}/versions")

    assert [item["public_id"] for item in response.json()] == [str(version.public_id)]
