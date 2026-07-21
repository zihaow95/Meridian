"""Create and publish immutable metric definition versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.operations.models import (
    CalculationType,
    MetricDefinitionStatus,
    MetricDefinitionVersion,
    overlapping_published_metrics,
    validate_metric_parameters,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.platform.outbox.services import OutboxMessage, register_outbox_event


def _next_version_number(*, organization_id: int, metric_code: str) -> int:
    latest = (
        MetricDefinitionVersion.objects.filter(
            organization_id=organization_id,
            metric_code=metric_code,
        )
        .order_by("-version_number")
        .first()
    )
    return 1 if latest is None else latest.version_number + 1


@dataclass
class CreateMetricDefinitionDraft:
    context: CommandContext
    metric_code: str
    name: str
    value_type: str
    unit: str
    currency: str
    source_field_codes: list[str]
    calculation_type: str
    aggregation_rule: dict[str, Any]
    window_definition: dict[str, Any]
    coverage_requirement: dict[str, Any]
    valid_from: datetime
    valid_to: datetime | None = None
    controlled_rule_code: str = ""
    parameters_json: dict[str, Any] | None = None

    def execute(self) -> MetricDefinitionVersion:
        actor = self.context.actor
        params = self.parameters_json or {}

        with transaction.atomic():
            decision = authorize(
                subject_for(actor),
                action="metric_rule.configure",
                resource=ResourceDescriptor(
                    resource_type="metric_definition",
                    public_id=None,
                    organization_id=actor.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if self.calculation_type not in CalculationType.values:
                raise ValidationFailedError(
                    message=f"Unsupported calculation_type: {self.calculation_type}"
                )
            param_errors = validate_metric_parameters(params)
            if param_errors:
                raise ValidationFailedError(
                    message="Metric parameters rejected.",
                    details={"errors": param_errors},
                )
            if (
                self.calculation_type == CalculationType.CONTROLLED_RULE
                and not self.controlled_rule_code
            ):
                raise ValidationFailedError(
                    message="controlled_rule_code is required for CONTROLLED_RULE."
                )

            version_number = _next_version_number(
                organization_id=actor.organization_id,
                metric_code=self.metric_code,
            )
            return MetricDefinitionVersion.objects.create(
                organization_id=actor.organization_id,
                metric_code=self.metric_code,
                name=self.name,
                version_number=version_number,
                value_type=self.value_type,
                unit=self.unit,
                currency=self.currency,
                source_field_codes=self.source_field_codes,
                calculation_type=self.calculation_type,
                aggregation_rule=self.aggregation_rule,
                window_definition=self.window_definition,
                coverage_requirement=self.coverage_requirement,
                controlled_rule_code=self.controlled_rule_code,
                parameters_json=params,
                valid_from=self.valid_from,
                valid_to=self.valid_to,
                status=MetricDefinitionStatus.DRAFT,
                created_by=actor,
            )


@dataclass
class PublishMetricDefinition:
    context: CommandContext
    metric_public_id: UUID

    def execute(self) -> MetricDefinitionVersion:
        actor = self.context.actor
        now = self.context.occurred_at

        with transaction.atomic():
            metric = (
                MetricDefinitionVersion.objects.select_for_update()
                .filter(
                    public_id=self.metric_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if metric is None:
                raise PermissionDeniedError()

            decision = authorize(
                subject_for(actor),
                action="metric_rule.configure",
                resource=ResourceDescriptor(
                    resource_type="metric_definition",
                    public_id=metric.public_id,
                    organization_id=metric.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed:
                raise PermissionDeniedError()

            if metric.status != MetricDefinitionStatus.DRAFT:
                raise ValidationFailedError(
                    message=f"Cannot publish metric in status {metric.status}"
                )

            param_errors = validate_metric_parameters(metric.parameters_json or {})
            if param_errors:
                raise ValidationFailedError(
                    message="Metric parameters rejected.",
                    details={"errors": param_errors},
                )

            if overlapping_published_metrics(
                organization_id=metric.organization_id,
                metric_code=metric.metric_code,
                valid_from=metric.valid_from,
                valid_to=metric.valid_to,
                exclude_id=metric.id,
            ).exists():
                raise ValidationFailedError(
                    message="Overlapping published metric effective window."
                )

            metric.status = MetricDefinitionStatus.PUBLISHED
            metric.published_by = actor
            metric.published_at = now
            metric.save(update_fields=["status", "published_by", "published_at", "updated_at"])

            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="metric_rule.configure",
                    resource_type="metric_definition",
                    resource_public_id=metric.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "metric_code": metric.metric_code,
                        "version_number": metric.version_number,
                        "calculation_type": metric.calculation_type,
                    },
                )
            )
            register_outbox_event(
                OutboxMessage(
                    event_type="metric_definition.published",
                    aggregate_type="metric_definition",
                    aggregate_id=metric.public_id,
                    payload={
                        "metric_code": metric.metric_code,
                        "version_number": metric.version_number,
                    },
                    occurred_at=now,
                )
            )
            return metric
