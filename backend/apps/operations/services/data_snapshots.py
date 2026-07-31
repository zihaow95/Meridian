"""Create immutable operating data snapshots with SHA-256 content hash."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils.dateparse import parse_date

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.operations.errors import MetricDataInsufficient, MetricDefinitionNotPublished
from apps.operations.models import (
    AggregateGrainType,
    MetricAggregate,
    MetricDefinitionStatus,
    MetricDefinitionVersion,
    OperatingDataSnapshot,
)
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.products.models import SKU, ChannelConfiguration, ProductAsset


def _authorize_read(actor: User) -> None:
    decision = authorize(
        subject_for(actor),
        action="operating_fact.read",
        resource=ResourceDescriptor(
            resource_type="operating_fact",
            public_id=None,
            organization_id=actor.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()


def _parse_period(value: str) -> date:
    parsed = parse_date(value)
    if parsed is None:
        raise ValidationFailedError(message=f"Invalid period date: {value}")
    return parsed


@dataclass
class CreateOperatingDataSnapshot:
    context: CommandContext
    purpose: str
    scope: dict[str, Any]
    periods: list[dict[str, Any]]
    metric_codes: list[str]

    def execute(self) -> OperatingDataSnapshot:
        actor = self.context.actor
        with transaction.atomic():
            _authorize_read(actor)
            organization_id = actor.organization_id

            product_ids = self.scope.get("product_public_ids") or []
            sku_ids = self.scope.get("sku_public_ids") or []
            channel_ids = self.scope.get("channel_public_ids") or []

            products = list(
                ProductAsset.objects.filter(
                    organization_id=organization_id, public_id__in=product_ids
                )
            )
            skus = list(SKU.objects.filter(organization_id=organization_id, public_id__in=sku_ids))
            channels = list(
                ChannelConfiguration.objects.filter(
                    organization_id=organization_id, public_id__in=channel_ids
                )
            )
            if (
                len(products) != len(product_ids)
                or len(skus) != len(sku_ids)
                or len(channels) != len(channel_ids)
            ):
                raise ValidationFailedError(message="Snapshot scope references unknown objects.")

            metrics_payload: list[dict[str, Any]] = []
            for period in self.periods:
                period_granularity = period["period_granularity"]
                period_start = _parse_period(period["period_start"])
                period_end = _parse_period(period["period_end"])
                for metric_code in self.metric_codes:
                    metric = (
                        MetricDefinitionVersion.objects.filter(
                            organization_id=organization_id,
                            metric_code=metric_code,
                            status=MetricDefinitionStatus.PUBLISHED,
                        )
                        .order_by("-version_number")
                        .first()
                    )
                    if metric is None:
                        raise MetricDefinitionNotPublished(
                            message=f"Metric definition not published: {metric_code}",
                            details={"metric_code": metric_code},
                        )

                    grain_filters: list[tuple[str, UUID]] = [
                        (AggregateGrainType.PRODUCT.value, p.public_id) for p in products
                    ] + [(AggregateGrainType.SKU.value, s.public_id) for s in skus]

                    for grain_type, grain_id in grain_filters:
                        aggs = MetricAggregate.objects.filter(
                            organization_id=organization_id,
                            grain_type=grain_type,
                            grain_id=grain_id,
                            metric_definition=metric,
                            period_granularity=period_granularity,
                            period_start=period_start,
                            period_end=period_end,
                        ).select_related("channel")
                        # Prefer channel-scoped rows matching snapshot channels, else ALL
                        chosen = None
                        for agg in aggs:
                            if agg.channel is not None and str(agg.channel.public_id) in {
                                str(c.public_id) for c in channels
                            }:
                                chosen = agg
                                break
                        if chosen is None:
                            chosen = next((a for a in aggs if a.channel_key == "ALL"), None)
                        if chosen is None and aggs.exists():
                            chosen = aggs.first()
                        if chosen is None:
                            continue

                        fact_ids = [
                            c["public_id"]
                            for c in chosen.contributors_json
                            if c.get("type") in {"FACT", "MANUAL"}
                        ]
                        fact_summaries = [
                            {
                                "public_id": c.get("public_id"),
                                "type": c.get("type"),
                                "numeric_value": c.get("numeric_value"),
                                "sku_public_id": c.get("sku_public_id"),
                                "channel_public_id": c.get("channel_public_id"),
                                "is_manual": c.get("is_manual", False),
                            }
                            for c in chosen.contributors_json
                        ]
                        metrics_payload.append(
                            {
                                "metric_code": metric_code,
                                "metric_definition_public_id": str(metric.public_id),
                                "metric_version_number": metric.version_number,
                                "grain_type": chosen.grain_type,
                                "grain_id": str(chosen.grain_id),
                                "channel_public_id": (
                                    str(chosen.channel.public_id)
                                    if chosen.channel is not None
                                    else None
                                ),
                                "period_granularity": period_granularity,
                                "period_start": period["period_start"],
                                "period_end": period["period_end"],
                                "value": str(chosen.value) if chosen.value is not None else None,
                                "status": chosen.status,
                                "coverage_rate": str(chosen.coverage_rate),
                                "has_manual_value": chosen.has_manual_value,
                                "coverage_requirement": metric.coverage_requirement,
                                "threshold": metric.parameters_json,
                                "fact_ids": fact_ids,
                                "fact_summaries": fact_summaries,
                            }
                        )

            if self.metric_codes and self.periods and not metrics_payload:
                raise MetricDataInsufficient(
                    details={
                        "metric_codes": list(self.metric_codes),
                        "periods": list(self.periods),
                    }
                )

            scope_json = {
                "product_public_ids": [str(p.public_id) for p in products],
                "sku_public_ids": [str(s.public_id) for s in skus],
                "channel_public_ids": [str(c.public_id) for c in channels],
            }
            periods_json = list(self.periods)
            metric_codes = list(self.metric_codes)
            payload_json = {
                "scope": scope_json,
                "periods": periods_json,
                "metric_codes": metric_codes,
                "metrics": metrics_payload,
            }
            snapshot = OperatingDataSnapshot(
                organization_id=organization_id,
                purpose=self.purpose,
                scope_json=scope_json,
                periods_json=periods_json,
                metric_codes=metric_codes,
                payload_json=payload_json,
                created_by=actor,
            )
            snapshot.content_hash = snapshot.compute_content_hash()
            snapshot.save()
            return snapshot


_RETIREMENT_EVIDENCE_KEYS = (
    "sales",
    "gross_margin",
    "inventory",
    "near_expiry",
    "complaints",
)


@dataclass
class CreateRetirementEvidenceSnapshot:
    """Create a retirement-purpose snapshot with TRD completeness evidence fields."""

    context: CommandContext
    product_public_id: UUID
    evidence: dict[str, Any]
    metric_codes: list[str] | None = None
    periods: list[dict[str, Any]] | None = None

    def execute(self) -> OperatingDataSnapshot:
        actor = self.context.actor
        with transaction.atomic():
            _authorize_read(actor)
            product = ProductAsset.objects.filter(
                organization_id=actor.organization_id,
                public_id=self.product_public_id,
            ).first()
            if product is None:
                raise ValidationFailedError(message="Product not found.")

            payload = dict(self.evidence or {})
            missing = [key for key in _RETIREMENT_EVIDENCE_KEYS if key not in payload]
            if missing:
                raise ValidationFailedError(
                    message=f"Missing retirement evidence fields: {', '.join(missing)}"
                )
            payload.setdefault("coverage_status", "SUFFICIENT")
            scope_json = {"product_public_id": str(product.public_id)}
            metric_codes = list(self.metric_codes or ["GROSS_SALES"])
            periods_json = list(self.periods or [])
            snapshot = OperatingDataSnapshot(
                organization_id=actor.organization_id,
                purpose="retirement",
                scope_json=scope_json,
                periods_json=periods_json,
                metric_codes=metric_codes,
                payload_json=payload,
                created_by=actor,
            )
            snapshot.content_hash = snapshot.compute_content_hash()
            snapshot.save()
            return snapshot
