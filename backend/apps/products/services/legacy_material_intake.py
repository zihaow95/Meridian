"""Park a historical file in the triage queue without promoting it."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.documents.models import DocumentVersion
from apps.platform.application.command import CommandContext
from apps.products.models import LegacyMaterialSubmission


class LegacyMaterialIntakeFailed(Exception):
    pass


@dataclass(frozen=True)
class LegacyMaterialIntakeResult:
    submission: LegacyMaterialSubmission
    # Same bytes already parked under a different owner. Surfaced so the
    # reviewer decides; the intake itself never merges or drops anything.
    duplicate_candidates: list[LegacyMaterialSubmission]


@dataclass(frozen=True)
class CreateLegacyMaterialSubmission:
    context: CommandContext
    document_version_public_id: UUID
    owner_type: str
    owner_id: int
    idempotency_key: str
    source_note: str = ""
    original_file_date: date | None = None
    claimed_version: str = ""
    claimed_effective_from: date | None = None

    def execute(self) -> LegacyMaterialIntakeResult:
        actor = self.context.actor
        version = (
            DocumentVersion.objects.select_related("file_object")
            .filter(
                public_id=self.document_version_public_id,
                organization_id=actor.organization_id,
            )
            .first()
        )
        if version is None:
            raise LegacyMaterialIntakeFailed("The document version does not exist.")

        with transaction.atomic():
            existing = LegacyMaterialSubmission.objects.filter(
                organization_id=actor.organization_id,
                idempotency_key=self.idempotency_key,
            ).first()
            if existing is not None:
                return LegacyMaterialIntakeResult(
                    submission=existing,
                    duplicate_candidates=self._duplicates_of(existing),
                )

            submission = LegacyMaterialSubmission.objects.create(
                organization_id=actor.organization_id,
                document_version=version,
                owner_type=self.owner_type,
                owner_id=self.owner_id,
                submitted_by=actor,
                source_note=self.source_note,
                original_file_date=self.original_file_date,
                sha256=version.file_object.sha256,
                claimed_version=self.claimed_version,
                claimed_effective_from=self.claimed_effective_from,
                idempotency_key=self.idempotency_key,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="legacy_material.submission.create",
                    resource_type="legacy_material_submission",
                    resource_public_id=submission.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=timezone.now(),
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary=self._audit_summary(submission),
                )
            )

        return LegacyMaterialIntakeResult(
            submission=submission,
            duplicate_candidates=self._duplicates_of(submission),
        )

    def _duplicates_of(
        self, submission: LegacyMaterialSubmission
    ) -> list[LegacyMaterialSubmission]:
        return list(
            LegacyMaterialSubmission.objects.filter(
                organization_id=submission.organization_id,
                sha256=submission.sha256,
            )
            .exclude(owner_type=submission.owner_type, owner_id=submission.owner_id)
            .order_by("created_at")
        )

    def _audit_summary(self, submission: LegacyMaterialSubmission) -> dict[str, Any]:
        # Identifiers and claims only; the audit trail never carries file bytes.
        return {
            "document_version_public_id": str(self.document_version_public_id),
            "owner_type": submission.owner_type,
            "owner_id": submission.owner_id,
            "sha256": submission.sha256,
            "claimed_version": submission.claimed_version,
            "processing_status": submission.processing_status,
        }
