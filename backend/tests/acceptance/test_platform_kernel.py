"""Phase 1 platform kernel acceptance scenarios."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ResourceDescriptor,
)
from apps.authorization.models.role import DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.documents.services.uploads import CreateUploadSession, complete_upload
from apps.identity.models.user import UserStatus
from apps.identity.services.change_user_status import ChangeUserStatus
from apps.platform.outbox.models import ConsumerReceipt, OutboxStatus
from apps.platform.outbox.services import OutboxMessage, register_outbox_event
from apps.platform.outbox.tasks import dispatch_outbox_task
from tests.notifications.test_todo_api import create_todo_for


@pytest.mark.django_db(transaction=True)
def test_platform_kernel_happy_path(
    client: Client,
    platform_admin_user,
    active_user,
    grant_action,
    file_storage,
) -> None:
    grant_action(active_user, "notification.todo.read", "notification.todo")

    login_response = client.post(
        "/api/v1/auth/dev/login",
        data={"login_key": active_user.login_key},
        content_type="application/json",
    )
    assert login_response.status_code == 200

    me_response = client.get("/api/v1/me")
    assert me_response.status_code == 200
    assert me_response.json()["public_id"] == str(active_user.public_id)

    todo_response = client.get("/api/v1/todos/my")
    assert todo_response.status_code == 200

    denied_audit = client.get("/api/v1/audit/events")
    assert denied_audit.status_code == 404

    grant_action(active_user, "identity.user.status_change", "identity.user")
    ChangeUserStatus(
        actor=active_user,
        target=active_user,
        status=UserStatus.DISABLED,
    ).execute()
    active_user.status = UserStatus.ACTIVE
    active_user.save(update_fields=["status", "updated_at"])

    create_todo_for(active_user, title="Acceptance Todo")

    append_event(
        AuditRecord(
            actor=active_user,
            action_code="identity.user.status_change",
            resource_type="identity.user",
            resource_public_id=active_user.public_id,
            result=AuditResult.SUCCESS,
            trace_id="acceptance-trace",
            occurred_at=timezone.now(),
            after_summary={"status": UserStatus.ACTIVE},
        )
    )

    outbox_event = register_outbox_event(
        OutboxMessage(
            event_type="todo.requested",
            aggregate_type="identity.user",
            aggregate_id=uuid4(),
            payload={
                "assignee_id": active_user.id,
                "organization_id": active_user.organization_id,
                "todo_type": "review",
                "source_type": "identity.user",
                "source_id": str(uuid4()),
                "action_code": "identity.user.review",
                "dedup_key": f"acceptance:{uuid4()}",
                "deep_link": "/admin/audit",
                "title": "Outbox Todo",
            },
            occurred_at=timezone.now(),
        )
    )
    dispatch_outbox_task(limit=10)
    outbox_event.refresh_from_db()
    assert outbox_event.status == OutboxStatus.PUBLISHED
    assert ConsumerReceipt.objects.filter(event=outbox_event).exists()

    session = CreateUploadSession(
        actor=active_user,
        original_filename="acceptance.pdf",
        declared_mime_type="application/pdf",
        storage=file_storage,
    ).execute()
    content = b"%PDF-1.4 acceptance"
    path = Path(session.temp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    session.size_bytes = len(content)
    session.sha256 = hashlib.sha256(content).hexdigest()
    session.save(update_fields=["size_bytes", "sha256"])

    version = complete_upload(session.public_id, actor=active_user, storage=file_storage)
    assert version.status == "CONTROLLED"

    todo_response = client.get("/api/v1/todos/my")
    assert todo_response.status_code == 200
    titles = [row["title"] for row in todo_response.json()]
    assert "Acceptance Todo" in titles

    highly_sensitive = ResourceDescriptor(
        resource_type="product.formula",
        public_id=uuid4(),
        organization_id=platform_admin_user.organization_id,
        sensitivity_level=DataSensitivityLevel.HIGHLY_SENSITIVE,
    )
    decision = authorize(
        AuthorizationSubject(user=platform_admin_user, role_codes=frozenset({"SYSTEM_ADMIN"})),
        action="product.formula.read",
        resource=highly_sensitive,
        context=AuthorizationContext.current(),
    )
    assert decision.allowed is False
