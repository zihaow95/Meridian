"""Operations API happy-path smoke and idempotency."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.identity.models.department import Department
from apps.identity.models.user import User
from apps.integrations.models import (
    DataSource,
    DataSourceStatus,
    DataSourceType,
    IngestionBatch,
    IngestionBatchStatus,
)
from apps.operations.models import (
    MonitoringScopeType,
    OperatingDataSnapshot,
    RiskCoverageStatus,
    RiskRuleStatus,
    RiskRuleVersion,
    RiskSignal,
    RiskSignalStatus,
)


@pytest.mark.django_db(transaction=True)
def test_create_and_publish_metric_via_api(
    api_client: APIClient,
    active_user: User,
    grant_action,
) -> None:
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    api_client.force_authenticate(user=active_user)
    now = timezone.now()

    create = api_client.post(
        "/api/v1/operating-metrics",
        {
            "metric_code": "API_GROSS_SALES",
            "name": "API Gross sales",
            "value_type": "DECIMAL",
            "unit": "CNY",
            "currency": "CNY",
            "source_field_codes": ["sales_amount"],
            "calculation_type": "SUM",
            "aggregation_rule": {"by": ["SKU", "CHANNEL"]},
            "window_definition": {"granularity": "MONTH"},
            "coverage_requirement": {"minimum_rate": "0.8"},
            "valid_from": now.isoformat(),
        },
        format="json",
    )
    assert create.status_code == 201
    draft_id = create.json()["public_id"]

    publish = api_client.post(f"/api/v1/operating-metrics/{draft_id}/publish", {}, format="json")
    assert publish.status_code == 200
    assert publish.json()["status"] == "PUBLISHED"
    assert publish.json()["public_id"] == draft_id


@pytest.mark.django_db(transaction=True)
def test_risk_signal_view_and_close_via_api(
    api_client: APIClient,
    active_user: User,
    grant_action,
    organization,
) -> None:
    grant_action(active_user, "risk_signal.read", "risk_signal")
    grant_action(active_user, "risk_signal.close", "risk_signal")
    rule = RiskRuleVersion.objects.create(
        organization=organization,
        rule_code="TEST_RULE",
        name="Test rule",
        version_number=1,
        metric_codes=["PRODUCTION_QTY"],
        evaluator_code="quarter_shelf_life_min_production",
        parameters_json={"min_production": "1000"},
        scope_type=MonitoringScopeType.SKU_CHANNEL,
        status=RiskRuleStatus.PUBLISHED,
        valid_from=timezone.now() - timedelta(days=30),
        created_by=active_user,
        published_by=active_user,
        published_at=timezone.now(),
    )
    snapshot = OperatingDataSnapshot(
        organization=organization,
        purpose="risk_signal",
        scope_json={},
        periods_json=[],
        metric_codes=["PRODUCTION_QTY"],
        payload_json={},
        created_by=active_user,
    )
    snapshot.content_hash = snapshot.compute_content_hash()
    snapshot.save()
    scope_id = uuid4()
    signal = RiskSignal.objects.create(
        organization=organization,
        rule_version=rule,
        scope_type=MonitoringScopeType.SKU_CHANNEL,
        scope_id=scope_id,
        scope_key=f"SKU_CHANNEL:{scope_id}:NONE",
        period_start=timezone.now().date(),
        period_end=(timezone.now() + timedelta(days=90)).date(),
        period_granularity="QUARTER",
        status=RiskSignalStatus.NEW,
        coverage_status=RiskCoverageStatus.SUFFICIENT,
        formula_snapshot={"threshold": "100"},
        actual_value=Decimal("50"),
        threshold_value=Decimal("100"),
        data_snapshot=snapshot,
    )
    api_client.force_authenticate(user=active_user)

    viewed = api_client.post(f"/api/v1/risk-signals/{signal.public_id}/view", {}, format="json")
    assert viewed.status_code == 200
    assert viewed.json()["status"] == "VIEWED"

    closed = api_client.post(
        f"/api/v1/risk-signals/{signal.public_id}/close",
        {"reason": "Reviewed and accepted"},
        format="json",
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "CLOSED"


@pytest.mark.django_db(transaction=True)
def test_confirm_batch_idempotent_via_api(
    api_client: APIClient,
    active_user: User,
    grant_action,
    organization,
) -> None:
    grant_action(active_user, "ingestion_batch.confirm", "ingestion_batch")
    department = Department.objects.create(
        organization=organization,
        name="Ops",
        department_code="OPS",
        valid_from=timezone.now(),
    )
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code="operating_source_mapping.idem",
        name="Idem mapping",
    )
    config = ConfigurationVersion.objects.create(
        organization=organization,
        definition=definition,
        version_number=1,
        status=ConfigurationStatus.PUBLISHED,
        content_json={"fields": []},
        created_by=active_user,
        published_by=active_user,
        published_at=timezone.now(),
    )
    source = DataSource.objects.create(
        organization=organization,
        source_code="IDEM_SRC",
        name="Idem source",
        source_type=DataSourceType.MANUAL,
        owner_department=department,
        sensitivity_level="INTERNAL",
        status=DataSourceStatus.ACTIVE,
        configuration_version=config,
    )
    batch = IngestionBatch.objects.create(
        organization=organization,
        source=source,
        batch_key="idem-1",
        source_type=DataSourceType.MANUAL,
        status=IngestionBatchStatus.SUCCESS,
        added_count=2,
        revision_count=0,
        skipped_count=1,
        error_count=0,
        warning_count=0,
        created_by=active_user,
    )
    api_client.force_authenticate(user=active_user)
    payload = {"idempotency_key": "confirm-idem-1"}

    first = api_client.post(
        f"/api/v1/operating-data/batches/{batch.public_id}/confirm",
        payload,
        format="json",
    )
    second = api_client.post(
        f"/api/v1/operating-data/batches/{batch.public_id}/confirm",
        payload,
        format="json",
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["added_count"] == 2
    assert first.json()["skipped_count"] == 1
