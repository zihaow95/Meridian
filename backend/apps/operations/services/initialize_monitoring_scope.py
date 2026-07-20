"""Initialize a minimal monitoring scope for an operating product."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db import IntegrityError

from apps.identity.models.user import User
from apps.operations.models import MonitoringScope, MonitoringScopeStatus
from apps.products.models import ProductVersion
from apps.projects.models import Project


@dataclass
class InitializeMonitoringScope:
    project: Project
    product_version: ProductVersion
    owner: User
    source_decision_public_id: UUID
    effective_at: datetime

    def execute(self) -> MonitoringScope:
        existing = MonitoringScope.objects.filter(
            project=self.project,
            source_decision_public_id=self.source_decision_public_id,
        ).first()
        if existing is not None:
            return existing
        try:
            return MonitoringScope.objects.create(
                organization=self.project.organization,
                project=self.project,
                product_version=self.product_version,
                owner=self.owner,
                effective_at=self.effective_at,
                status=MonitoringScopeStatus.ACTIVE,
                source_decision_public_id=self.source_decision_public_id,
            )
        except IntegrityError:
            return MonitoringScope.objects.get(
                project=self.project,
                source_decision_public_id=self.source_decision_public_id,
            )
