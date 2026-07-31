"""Governed operating data export with download tickets."""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import LEVEL_RANK, DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.documents.services.ingest import activate_staged_content, stage_controlled_content
from apps.documents.services.tickets import IssueDownloadTicket
from apps.documents.storage.factory import get_file_storage
from apps.identity.models.user import User
from apps.operations.models import MetricAggregate, OperatingFact
from apps.operations.queries.visible_resources import (
    user_max_data_level,
    visible_product_public_ids_for_export,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import SKU


@dataclass(frozen=True)
class OperatingExportResult:
    document_version_public_id: UUID
    token: str
    expires_at: str


_SENSITIVE_VALUE_MIN = DataSensitivityLevel.SENSITIVE_CONTROLLED


def _authorize_export(actor: User) -> None:
    decision = authorize(
        subject_for(actor),
        action="operating_detail.export",
        resource=ResourceDescriptor(
            resource_type="operating_fact",
            public_id=None,
            organization_id=actor.organization_id,
            sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _redact_value(value: Decimal | None, *, max_level: str) -> str:
    if value is None:
        return ""
    if LEVEL_RANK.get(max_level, 0) < LEVEL_RANK.get(_SENSITIVE_VALUE_MIN, 0):
        return "[REDACTED]"
    return str(value)


@dataclass
class CreateOperatingDataExport:
    context: CommandContext
    period_start: date
    period_end: date
    period_granularity: str
    metric_codes: list[str] | None = None

    def execute(self) -> OperatingExportResult:
        actor = self.context.actor
        now = self.context.occurred_at or timezone.now()
        if self.period_end < self.period_start:
            raise ValidationFailedError(message="period_end must be on or after period_start.")

        _authorize_export(actor)
        max_level = user_max_data_level(actor)
        visible_products = visible_product_public_ids_for_export(actor)

        facts = OperatingFact.objects.filter(
            organization_id=actor.organization_id,
            period_start__gte=self.period_start,
            period_end__lte=self.period_end,
            period_granularity=self.period_granularity,
        ).select_related("sku", "channel", "metric_definition")
        aggregates = MetricAggregate.objects.filter(
            organization_id=actor.organization_id,
            period_start=self.period_start,
            period_end=self.period_end,
            period_granularity=self.period_granularity,
        ).select_related("metric_definition", "channel")

        if self.metric_codes:
            facts = facts.filter(metric_definition__metric_code__in=self.metric_codes)
            aggregates = aggregates.filter(metric_definition__metric_code__in=self.metric_codes)

        if visible_products is not None:
            sku_public_ids = set(
                SKU.objects.filter(
                    organization_id=actor.organization_id,
                    product_version__product__public_id__in=visible_products,
                ).values_list("public_id", flat=True)
            )
            facts = facts.filter(sku__public_id__in=sku_public_ids)
            aggregates = aggregates.filter(grain_id__in=sku_public_ids | visible_products)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "row_type",
                "metric_code",
                "grain_or_sku",
                "channel",
                "period_start",
                "period_end",
                "period_granularity",
                "value",
                "status",
            ]
        )
        for fact in facts.order_by("period_start", "id")[:5000]:
            writer.writerow(
                [
                    "fact",
                    fact.metric_definition.metric_code,
                    str(fact.sku.public_id),
                    str(fact.channel.public_id) if fact.channel_id else "",
                    str(fact.period_start),
                    str(fact.period_end),
                    fact.period_granularity,
                    _redact_value(fact.numeric_value, max_level=max_level),
                    fact.fact_status,
                ]
            )
        for row in aggregates.order_by("period_start", "id")[:5000]:
            writer.writerow(
                [
                    "aggregate",
                    row.metric_definition.metric_code,
                    str(row.grain_id),
                    str(row.channel.public_id) if row.channel is not None else "",
                    str(row.period_start),
                    str(row.period_end),
                    row.period_granularity,
                    _redact_value(row.value, max_level=max_level),
                    row.status,
                ]
            )

        payload = buffer.getvalue().encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        storage = get_file_storage()
        temp_path = storage.temp_dir() / f"operating-export-{actor.public_id}.csv"
        temp_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_bytes(payload)

        with transaction.atomic():
            version, staged = stage_controlled_content(
                organization=actor.organization,
                source_temp_path=temp_path,
                sha256=digest,
                size_bytes=len(payload),
                original_filename="operating-export.csv",
                mime_type="text/csv",
                uploaded_by=actor,
                source="operating_export",
                category="operating_data",
                title="Operating data export",
                sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="operating_detail.export",
                    resource_type="operating_fact",
                    resource_public_id=version.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=now,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "period_start": str(self.period_start),
                        "period_end": str(self.period_end),
                        "period_granularity": self.period_granularity,
                        "document_version_public_id": str(version.public_id),
                    },
                )
            )

        activated = activate_staged_content(staged, storage)
        ticket, token = IssueDownloadTicket(actor=actor, version=activated).execute()
        return OperatingExportResult(
            document_version_public_id=activated.public_id,
            token=token,
            expires_at=ticket.expires_at.isoformat(),
        )
