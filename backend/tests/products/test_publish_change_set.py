"""Atomic product change set publication."""

from __future__ import annotations

import pytest
from django.db import DatabaseError

from apps.platform.application.command import CommandContext
from apps.products.errors import ChangeSetAlreadyPublished, ProductPublicationFailed
from apps.products.models import ChangeSetStatus, ProductVersion
from apps.products.services.publish_change_set import PublishProductChangeSet


def raise_database_error(*_args, **_kwargs) -> None:
    raise DatabaseError("simulated publication failure")


@pytest.mark.django_db(transaction=True)
def test_publish_failure_keeps_effective_dossier_unchanged(ready_change_set, monkeypatch) -> None:
    before_primary_version = ready_change_set.product.primary_version_id
    monkeypatch.setattr(
        "apps.products.services.publish_change_set.create_channel_configurations",
        raise_database_error,
    )
    with pytest.raises(ProductPublicationFailed):
        PublishProductChangeSet(
            context=CommandContext.for_actor(ready_change_set.approved_by),
            change_set_public_id=ready_change_set.public_id,
            idempotency_key="publish-fails",
        ).execute()
    ready_change_set.product.refresh_from_db()
    ready_change_set.refresh_from_db()
    assert ready_change_set.product.primary_version_id == before_primary_version
    assert ready_change_set.status == ChangeSetStatus.APPROVED


@pytest.mark.django_db(transaction=True)
def test_repeated_publish_returns_first_result(ready_change_set) -> None:
    first = PublishProductChangeSet(
        context=CommandContext.for_actor(ready_change_set.approved_by),
        change_set_public_id=ready_change_set.public_id,
        idempotency_key="publish-1",
    ).execute()
    second = PublishProductChangeSet(
        context=CommandContext.for_actor(ready_change_set.approved_by),
        change_set_public_id=ready_change_set.public_id,
        idempotency_key="publish-1",
    ).execute()
    assert first.product_version.public_id == second.product_version.public_id
    assert ProductVersion.objects.filter(change_set=ready_change_set).count() == 1


@pytest.mark.django_db(transaction=True)
def test_second_publish_with_different_idempotency_key_is_rejected(ready_change_set) -> None:
    PublishProductChangeSet(
        context=CommandContext.for_actor(ready_change_set.approved_by),
        change_set_public_id=ready_change_set.public_id,
        idempotency_key="publish-1",
    ).execute()
    with pytest.raises(ChangeSetAlreadyPublished):
        PublishProductChangeSet(
            context=CommandContext.for_actor(ready_change_set.approved_by),
            change_set_public_id=ready_change_set.public_id,
            idempotency_key="publish-2",
        ).execute()
