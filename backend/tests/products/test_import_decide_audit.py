"""Import item decision audit and outbox facts."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.audit.models import AuditEvent
from apps.identity.models.user import User
from apps.platform.application.command import CommandContext
from apps.platform.outbox.models import OutboxEvent
from apps.products.models import ImportItemDecision
from apps.products.services.import_batch import CreateProductImportBatch, DecideImportItem
from apps.products.services.import_template import sample_import_csv


@pytest.fixture
def reviewer(product_director: User, grant_action: Callable[..., None]) -> User:
    grant_action(product_director, "migration.upload", "migration", role_code="PRODUCT_DIRECTOR")
    grant_action(product_director, "migration.review", "migration", role_code="PRODUCT_DIRECTOR")
    return product_director


@pytest.mark.django_db
def test_decide_import_item_writes_audit_and_outbox(reviewer: User) -> None:
    batch = CreateProductImportBatch(
        context=CommandContext.for_actor(reviewer),
        csv_content=sample_import_csv(),
        source_filename="decide-audit.csv",
    ).execute()
    item = DecideImportItem(
        context=CommandContext.for_actor(reviewer),
        batch_public_id=batch.public_id,
        row_number=1,
        decision=ImportItemDecision.CREATE,
    ).execute()
    assert item.decision == ImportItemDecision.CREATE
    assert AuditEvent.objects.filter(
        action_code="migration.review",
        resource_type="migration",
        resource_public_id=batch.public_id,
    ).exists()
    assert OutboxEvent.objects.filter(
        event_type="import_item.decided",
        aggregate_id=batch.public_id,
    ).exists()
