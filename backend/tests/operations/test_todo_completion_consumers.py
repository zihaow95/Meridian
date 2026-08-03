"""Consumers complete todos via notifications domain service."""

from __future__ import annotations

from uuid import uuid4

import pytest
from django.utils import timezone

from apps.notifications.models import Todo, TodoStatus
from apps.notifications.services.todos import CompleteOpenTodosForSource
from apps.operations.consumers import (
    OperatingIssueConvertedConsumer,
    RetirementCompletedConsumer,
)
from apps.operations.models import (
    IssueSourceType,
    OperatingIssue,
    OperatingIssueStatus,
    RetirementPlan,
    RetirementPlanStatus,
)
from apps.platform.outbox.models import OutboxEvent, OutboxStatus
from apps.products.models import (
    ProductAsset,
    ProductLifecycleStatus,
    ProductSourceType,
)


def _product(organization, owner) -> ProductAsset:
    return ProductAsset.objects.create(
        organization=organization,
        business_no=f"PRD-TODO-{uuid4().hex[:6].upper()}",
        name="Todo yogurt",
        category_code="YOGURT",
        source_type=ProductSourceType.NEW_PROJECT,
        lifecycle_status=ProductLifecycleStatus.ACTIVE,
        product_owner=owner,
    )


@pytest.mark.django_db
def test_complete_open_todos_for_source_is_idempotent(organization, active_user) -> None:
    source_id = uuid4()
    Todo.objects.create(
        organization=organization,
        assignee=active_user,
        todo_type="operating_issue_review",
        source_type="operating_issue",
        source_id=source_id,
        action_code="operating_issue.analyze",
        status=TodoStatus.OPEN,
        dedup_key=f"open:{source_id}",
        deep_link="/x",
        title="Open",
    )
    Todo.objects.create(
        organization=organization,
        assignee=active_user,
        todo_type="operating_issue_review",
        source_type="operating_issue",
        source_id=source_id,
        action_code="operating_issue.analyze",
        status=TodoStatus.COMPLETED,
        dedup_key=f"done:{source_id}",
        deep_link="/x",
        title="Done",
    )
    assert (
        CompleteOpenTodosForSource(
            organization_id=organization.id,
            source_type="operating_issue",
            source_id=source_id,
            actor=active_user,
        ).execute()
        == 1
    )
    assert Todo.objects.filter(source_id=source_id, status=TodoStatus.OPEN).count() == 0
    assert (
        CompleteOpenTodosForSource(
            organization_id=organization.id,
            source_type="operating_issue",
            source_id=source_id,
            actor=active_user,
        ).execute()
        == 0
    )


@pytest.mark.django_db
def test_operating_issue_converted_consumer_completes_open_todos(organization, active_user) -> None:
    product = _product(organization, active_user)
    issue = OperatingIssue.objects.create(
        organization=organization,
        product=product,
        business_no=f"ISS-{uuid4().hex[:6].upper()}",
        title="Issue",
        phenomenon_summary="summary",
        source_type=IssueSourceType.DIRECT,
        owner=active_user,
        created_by=active_user,
        status=OperatingIssueStatus.CONVERTED_TO_PROPOSAL,
        version_no=1,
    )
    Todo.objects.create(
        organization=organization,
        assignee=active_user,
        todo_type="operating_issue_review",
        source_type="operating_issue",
        source_id=issue.public_id,
        action_code="operating_issue.analyze",
        status=TodoStatus.OPEN,
        dedup_key=f"issue:{issue.public_id}",
        deep_link=f"/operations/issues/{issue.public_id}",
        title=issue.title,
    )
    event = OutboxEvent.objects.create(
        event_type="operating_issue.converted",
        aggregate_type="operating_issue",
        aggregate_id=issue.public_id,
        payload_json={"issue_public_id": str(issue.public_id)},
        occurred_at=timezone.now(),
        status=OutboxStatus.PENDING,
    )
    OperatingIssueConvertedConsumer().consume(event)
    assert Todo.objects.filter(source_id=issue.public_id, status=TodoStatus.OPEN).count() == 0
    assert Todo.objects.filter(source_id=issue.public_id, status=TodoStatus.COMPLETED).count() == 1


@pytest.mark.django_db
def test_retirement_completed_consumer_completes_open_todos(organization, active_user) -> None:
    product = _product(organization, active_user)
    issue = OperatingIssue.objects.create(
        organization=organization,
        product=product,
        business_no=f"ISS-{uuid4().hex[:6].upper()}",
        title="Retire issue",
        phenomenon_summary="summary",
        source_type=IssueSourceType.DIRECT,
        owner=active_user,
        created_by=active_user,
        status=OperatingIssueStatus.RETIREMENT_REVIEW,
        version_no=1,
    )
    plan = RetirementPlan.objects.create(
        organization=organization,
        product=product,
        issue=issue,
        status=RetirementPlanStatus.COMPLETED,
        created_by=active_user,
        scope_snapshot={},
        inventory_plan={},
        supply_contract_impact={},
        customer_market_plan={},
        replacement_plan={},
        stop_production_at=timezone.now().date(),
        stop_sale_at=timezone.now().date(),
        retire_at=timezone.now().date(),
    )
    Todo.objects.create(
        organization=organization,
        assignee=active_user,
        todo_type="retirement_execution",
        source_type="retirement_plan",
        source_id=plan.public_id,
        action_code="retirement_plan.execute",
        status=TodoStatus.OPEN,
        dedup_key=f"plan:{plan.public_id}",
        deep_link=f"/operations/retirement/{plan.public_id}",
        title="Execute",
    )
    event = OutboxEvent.objects.create(
        event_type="retirement.completed",
        aggregate_type="retirement_plan",
        aggregate_id=plan.public_id,
        payload_json={"plan_public_id": str(plan.public_id)},
        occurred_at=timezone.now(),
        status=OutboxStatus.PENDING,
    )
    RetirementCompletedConsumer().consume(event)
    assert Todo.objects.filter(source_id=plan.public_id, status=TodoStatus.OPEN).count() == 0
