"""Metric definition versions: controlled calculators and immutable publish."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.identity.models.user import User
from apps.operations.models import (
    CalculationType,
    MetricDefinitionStatus,
    PublishedMetricImmutable,
)
from apps.operations.services.metric_definitions import (
    CreateMetricDefinitionDraft,
    PublishMetricDefinition,
)
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext


def _draft_kwargs(**overrides):
    now = timezone.now()
    base = {
        "metric_code": "GROSS_SALES",
        "name": "Gross sales",
        "value_type": "DECIMAL",
        "unit": "CNY",
        "currency": "CNY",
        "source_field_codes": ["sales_amount"],
        "calculation_type": CalculationType.SUM,
        "aggregation_rule": {"by": ["SKU", "CHANNEL"]},
        "window_definition": {"granularity": "MONTH"},
        "coverage_requirement": {"minimum_rate": "0.8"},
        "valid_from": now,
        "valid_to": None,
    }
    base.update(overrides)
    return base


@pytest.mark.django_db(transaction=True)
def test_metric_code_versions_increment_on_publish(active_user: User, grant_action) -> None:
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)
    first_draft = CreateMetricDefinitionDraft(
        context=ctx,
        **_draft_kwargs(valid_from=timezone.now(), valid_to=timezone.now() + timedelta(days=29)),
    ).execute()
    first = PublishMetricDefinition(context=ctx, metric_public_id=first_draft.public_id).execute()
    second_draft = CreateMetricDefinitionDraft(
        context=ctx,
        **_draft_kwargs(valid_from=timezone.now() + timedelta(days=30)),
    ).execute()
    second = PublishMetricDefinition(context=ctx, metric_public_id=second_draft.public_id).execute()

    assert first.version_number == 1
    assert second.version_number == 2
    assert first.status == MetricDefinitionStatus.PUBLISHED
    assert second.status == MetricDefinitionStatus.PUBLISHED


@pytest.mark.django_db(transaction=True)
def test_published_metric_cannot_be_modified(active_user: User, grant_action) -> None:
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)
    draft = CreateMetricDefinitionDraft(context=ctx, **_draft_kwargs()).execute()
    published = PublishMetricDefinition(context=ctx, metric_public_id=draft.public_id).execute()

    with pytest.raises(PublishedMetricImmutable):
        published.name = "Tampered"
        published.save()


@pytest.mark.django_db(transaction=True)
def test_overlapping_effective_windows_are_rejected(active_user: User, grant_action) -> None:
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)
    now = timezone.now()
    first_draft = CreateMetricDefinitionDraft(
        context=ctx,
        **_draft_kwargs(valid_from=now, valid_to=now + timedelta(days=60)),
    ).execute()
    PublishMetricDefinition(context=ctx, metric_public_id=first_draft.public_id).execute()

    overlap = CreateMetricDefinitionDraft(
        context=ctx,
        **_draft_kwargs(valid_from=now + timedelta(days=30), valid_to=None),
    ).execute()
    with pytest.raises(ValidationFailedError):
        PublishMetricDefinition(context=ctx, metric_public_id=overlap.public_id).execute()


@pytest.mark.django_db(transaction=True)
def test_arbitrary_python_or_sql_expressions_are_rejected(active_user: User, grant_action) -> None:
    grant_action(active_user, "metric_rule.configure", "metric_definition")
    ctx = CommandContext.for_actor(active_user)

    with pytest.raises(ValidationFailedError):
        CreateMetricDefinitionDraft(
            context=ctx,
            **_draft_kwargs(
                calculation_type=CalculationType.CONTROLLED_RULE,
                controlled_rule_code="sales_ratio",
                parameters_json={"expression": "lambda x: x * 2"},
            ),
        ).execute()

    with pytest.raises(ValidationFailedError):
        CreateMetricDefinitionDraft(
            context=ctx,
            **_draft_kwargs(
                calculation_type=CalculationType.CONTROLLED_RULE,
                controlled_rule_code="sales_ratio",
                parameters_json={"sql": "SELECT 1"},
            ),
        ).execute()

    with pytest.raises(ValidationFailedError):
        CreateMetricDefinitionDraft(
            context=ctx,
            **_draft_kwargs(calculation_type="PYTHON_EVAL"),
        ).execute()
