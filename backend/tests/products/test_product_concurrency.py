"""Concurrency and single-writer guarantees for product publication."""

from __future__ import annotations

import pytest
from django.db import connection

from apps.platform.application.command import CommandContext
from apps.products.models import ProductVersion
from apps.products.services.publish_change_set import PublishProductChangeSet


@pytest.mark.django_db(transaction=True)
def test_publish_lock_prevents_duplicate_versions_under_retry(ready_change_set) -> None:
    actor = ready_change_set.approved_by
    context = CommandContext.for_actor(actor)
    first = PublishProductChangeSet(
        context=context,
        change_set_public_id=ready_change_set.public_id,
        idempotency_key="concurrent-publish",
    ).execute()

    connection.close()

    second = PublishProductChangeSet(
        context=context,
        change_set_public_id=ready_change_set.public_id,
        idempotency_key="concurrent-publish",
    ).execute()
    assert second.product_version.public_id == first.product_version.public_id
    assert ProductVersion.objects.filter(change_set=ready_change_set).count() == 1
