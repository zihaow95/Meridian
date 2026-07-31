"""Initialize a monitoring scope and default product-level assignment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.authorization.models.role import DataSensitivityLevel
from apps.identity.models.user import User
from apps.operations.models import (
    MonitoringAssignment,
    MonitoringAssignmentStatus,
    MonitoringScope,
    MonitoringScopeStatus,
    MonitoringScopeType,
    build_monitoring_scope_key,
)
from apps.products.models import ProductVersion
from apps.projects.models import Project


def ensure_default_product_assignment(
    *,
    scope: MonitoringScope,
    product_id: int,
    supervisor: User,
    effective_at: datetime,
) -> MonitoringAssignment:
    scope_key = build_monitoring_scope_key(
        scope_type=MonitoringScopeType.PRODUCT,
        product_id=product_id,
    )
    existing = MonitoringAssignment.objects.filter(
        monitoring_scope=scope,
        supervisor=supervisor,
        scope_key=scope_key,
        status=MonitoringAssignmentStatus.ACTIVE,
        active_slot=1,
    ).first()
    if existing is not None:
        return existing
    try:
        return MonitoringAssignment.objects.create(
            organization=scope.organization,
            monitoring_scope=scope,
            supervisor=supervisor,
            product_id=product_id,
            sku=None,
            channel=None,
            scope_type=MonitoringScopeType.PRODUCT,
            scope_key=scope_key,
            effective_from=effective_at,
            effective_to=None,
            status=MonitoringAssignmentStatus.ACTIVE,
            active_slot=1,
            max_data_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
        )
    except IntegrityError:
        return MonitoringAssignment.objects.get(
            monitoring_scope=scope,
            supervisor=supervisor,
            scope_key=scope_key,
            active_slot=1,
        )


@dataclass
class InitializeMonitoringScope:
    project: Project
    product_version: ProductVersion
    owner: User
    source_decision_public_id: UUID
    effective_at: datetime

    def execute(self) -> MonitoringScope:
        with transaction.atomic():
            existing = (
                MonitoringScope.objects.select_for_update()
                .filter(
                    project=self.project,
                    source_decision_public_id=self.source_decision_public_id,
                )
                .first()
            )
            if existing is not None:
                ensure_default_product_assignment(
                    scope=existing,
                    product_id=self.product_version.product_id,
                    supervisor=self.owner,
                    effective_at=existing.effective_at,
                )
                return existing
            try:
                scope = MonitoringScope.objects.create(
                    organization=self.project.organization,
                    project=self.project,
                    product_version=self.product_version,
                    owner=self.owner,
                    effective_at=self.effective_at,
                    status=MonitoringScopeStatus.ACTIVE,
                    source_decision_public_id=self.source_decision_public_id,
                )
            except IntegrityError:
                scope = MonitoringScope.objects.get(
                    project=self.project,
                    source_decision_public_id=self.source_decision_public_id,
                )
            ensure_default_product_assignment(
                scope=scope,
                product_id=self.product_version.product_id,
                supervisor=self.owner,
                effective_at=scope.effective_at,
            )
            return scope
