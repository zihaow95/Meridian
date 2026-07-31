"""Operations API query permission boundaries."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from rest_framework.test import APIClient

from apps.identity.models.user import User
from apps.products.models import (
    ProductAsset,
    ProductLifecycleStatus,
    ProductSourceType,
)


@pytest.mark.django_db(transaction=True)
def test_no_role_lists_are_empty_and_create_is_404_style(
    api_client: APIClient,
    active_user: User,
) -> None:
    api_client.force_authenticate(user=active_user)

    signals = api_client.get("/api/v1/risk-signals")
    assert signals.status_code == 200
    assert signals.json()["items"] == []

    issues = api_client.get("/api/v1/operating-issues")
    assert issues.status_code == 200
    assert issues.json()["items"] == []

    create = api_client.post(
        "/api/v1/operating-issues",
        {
            "title": "Denied",
            "product_public_id": str(uuid4()),
            "phenomenon_summary": "no grant",
            "source_type": "DIRECT",
            "source_materials_json": {"reason": "x"},
        },
        format="json",
    )
    assert create.status_code == 404
    assert create.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db(transaction=True)
def test_configure_only_platform_admin_cannot_read_summary_or_export(
    api_client: APIClient,
    active_user: User,
    grant_action,
    organization,
) -> None:
    grant_action(active_user, "data_source.configure", "data_source")
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-PERM",
        name="Perm product",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )
    api_client.force_authenticate(user=active_user)

    summary = api_client.get(
        f"/api/v1/products/{product.public_id}/operating-summary",
        {
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "period_granularity": "QUARTER",
        },
    )
    assert summary.status_code == 404
    assert summary.json()["code"] == "RESOURCE_NOT_FOUND"

    export = api_client.post(
        "/api/v1/operating-data/exports",
        {
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "period_granularity": "QUARTER",
        },
        format="json",
    )
    assert export.status_code == 404
    assert export.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db(transaction=True)
def test_read_allows_summary_but_export_requires_separate_action(
    api_client: APIClient,
    active_user: User,
    grant_action,
    organization,
) -> None:
    grant_action(active_user, "operating_fact.read", "operating_fact")
    product = ProductAsset.objects.create(
        organization=organization,
        business_no="PRD-READ",
        name="Read product",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=active_user,
    )
    api_client.force_authenticate(user=active_user)

    summary = api_client.get(
        f"/api/v1/products/{product.public_id}/operating-summary",
        {
            "period_start": str(date(2026, 1, 1)),
            "period_end": str(date(2026, 3, 31)),
            "period_granularity": "QUARTER",
        },
    )
    assert summary.status_code == 200
    body = summary.json()
    assert "items" in body

    export = api_client.post(
        "/api/v1/operating-data/exports",
        {
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "period_granularity": "QUARTER",
        },
        format="json",
    )
    assert export.status_code == 404
    assert export.json()["code"] == "RESOURCE_NOT_FOUND"
