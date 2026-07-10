"""Manage external system bindings for product objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from apps.integrations.models import BindingStatus, ExternalBinding
from apps.products.errors import ExternalBindingConflict


@dataclass(frozen=True)
class ExternalBindingInput:
    source_system: str
    object_type: str
    external_id: str
    internal_object_type: str
    internal_object_id: int
    source_timestamp: datetime | None = None


@dataclass
class UpsertExternalBinding:
    organization_id: int
    binding: ExternalBindingInput

    def execute(self) -> ExternalBinding:
        with transaction.atomic():
            conflict = (
                ExternalBinding.objects.select_for_update()
                .filter(
                    organization_id=self.organization_id,
                    source_system=self.binding.source_system,
                    object_type=self.binding.object_type,
                    external_id=self.binding.external_id,
                    binding_status=BindingStatus.ACTIVE,
                )
                .exclude(
                    internal_object_type=self.binding.internal_object_type,
                    internal_object_id=self.binding.internal_object_id,
                )
                .first()
            )
            if conflict is not None:
                raise ExternalBindingConflict()

            row, _created = ExternalBinding.objects.update_or_create(
                organization_id=self.organization_id,
                source_system=self.binding.source_system,
                object_type=self.binding.object_type,
                external_id=self.binding.external_id,
                defaults={
                    "internal_object_type": self.binding.internal_object_type,
                    "internal_object_id": self.binding.internal_object_id,
                    "source_timestamp": self.binding.source_timestamp,
                    "last_synced_at": self.binding.source_timestamp,
                    "binding_status": BindingStatus.ACTIVE,
                },
            )
        return row
