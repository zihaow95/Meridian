"""Attribute schema resolution and validation."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.platform.application.command import CommandContext
from apps.products.errors import (
    AttributeSchemaNotPublished,
    AttributeValueInvalid,
    ChangeSetVersionConflict,
)
from apps.products.models import (
    AttributeSchemaStatus,
    AttributeSchemaVersion,
)
from apps.products.services.attribute_schema import resolve_product_attribute_schema
from apps.products.services.edit_change_set import EditProductChangeSet


@pytest.mark.django_db
def test_unknown_attribute_code_is_rejected(change_set, published_product_schema) -> None:
    del published_product_schema
    service = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="PRODUCT_DEFINITION",
        values={"unexpected_field": "value"},
    )
    with pytest.raises(AttributeValueInvalid) as exc:
        service.execute()
    assert exc.value.code == "ATTRIBUTE_VALUE_INVALID"


@pytest.mark.django_db
def test_resolve_raises_when_schema_not_published(organization) -> None:
    AttributeSchemaVersion.objects.create(
        organization=organization,
        schema_code="PRODUCT_PROFILE",
        version_number=1,
        category_code="YOGURT",
        status=AttributeSchemaStatus.DRAFT,
    )
    with pytest.raises(AttributeSchemaNotPublished) as exc:
        resolve_product_attribute_schema(organization, category_code="YOGURT", as_of=timezone.now())
    assert exc.value.code == "ATTRIBUTE_SCHEMA_NOT_PUBLISHED"


@pytest.mark.django_db
def test_valid_edit_stores_content_hash(change_set, published_product_schema) -> None:
    del published_product_schema
    group_value = EditProductChangeSet(
        context=CommandContext.for_actor(change_set.created_by),
        change_set_public_id=change_set.public_id,
        version_no=change_set.version_no,
        group_code="PRODUCT_DEFINITION",
        values={"core_selling_points": "High protein"},
    ).execute()
    assert group_value.content_hash
    assert group_value.values_json == {"core_selling_points": "High protein"}
    change_set.refresh_from_db()
    assert change_set.version_no == 2


@pytest.mark.django_db
def test_change_set_version_conflict_rejects_stale_write(
    change_set, published_product_schema
) -> None:
    del published_product_schema
    with pytest.raises(ChangeSetVersionConflict):
        EditProductChangeSet(
            context=CommandContext.for_actor(change_set.created_by),
            change_set_public_id=change_set.public_id,
            version_no=999,
            group_code="PRODUCT_DEFINITION",
            values={"core_selling_points": "High protein"},
        ).execute()
