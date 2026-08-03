"""Turn verified historical files into a product material history.

Two steps, deliberately separate. Verification is a judgement about provenance:
is this really the file it claims to be, and did it really take effect when the
submitter says. Promotion is a bookkeeping act that arranges verified files into
a chain and names exactly one of them current. Neither step approves anything
professionally — that is `material_confirmations`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.products.models import (
    LegacyMaterialStatus,
    LegacyMaterialSubmission,
    MaterialStatus,
    ProductMaterial,
)

_DECIDABLE = frozenset({LegacyMaterialStatus.VERIFIED, LegacyMaterialStatus.REJECTED})


class MaterialChainRejected(Exception):
    """The requested promotion is not supported by verified evidence."""


@dataclass(frozen=True)
class MaterialOwner:
    owner_type: str
    owner_id: int


def make_material_current(material: ProductMaterial) -> ProductMaterial:
    """Move the current marker onto one material of a chain.

    The slot is released before it is claimed, so the unique index holds at
    every instant. Confirmations of the material being stood down are retired
    here rather than by the caller: an approval always describes bytes that are
    no longer the current ones.
    """

    from apps.products.services.material_confirmations import supersede_live_confirmations

    stood_down = (
        ProductMaterial.objects.select_for_update()
        .filter(
            organization_id=material.organization_id,
            owner_type=material.owner_type,
            owner_id=material.owner_id,
            material_type_code=material.material_type_code,
            current_slot=1,
        )
        .exclude(pk=material.pk)
    )
    for previous in stood_down:
        supersede_live_confirmations(previous)
    stood_down.update(current_slot=None, material_status=MaterialStatus.INACTIVE)

    material.current_slot = 1
    material.save(update_fields=["current_slot", "updated_at"])
    return material


@dataclass(frozen=True)
class VerifyLegacyMaterialSubmission:
    context: CommandContext
    submission_public_id: UUID
    decision: str
    note: str = ""

    def execute(self) -> LegacyMaterialSubmission:
        actor = self.context.actor
        if self.decision not in _DECIDABLE:
            raise MaterialChainRejected(f"{self.decision} is not a verification decision.")

        with transaction.atomic():
            submission = (
                LegacyMaterialSubmission.objects.select_for_update()
                .filter(
                    public_id=self.submission_public_id,
                    organization_id=actor.organization_id,
                )
                .first()
            )
            if submission is None:
                raise PermissionDeniedError()

            _require(
                actor,
                action="legacy_material.submission.verify",
                resource_type="legacy_material_submission",
                public_id=submission.public_id,
                organization_id=submission.organization_id,
            )

            if submission.processing_status != LegacyMaterialStatus.PENDING_TRIAGE:
                raise MaterialChainRejected(
                    "This submission was already decided; re-deciding would erase the "
                    "original judgement."
                )

            submission.processing_status = self.decision
            submission.verified_by = actor
            submission.verified_at = timezone.now()
            submission.verification_note = self.note
            submission.save(
                update_fields=[
                    "processing_status",
                    "verified_by",
                    "verified_at",
                    "verification_note",
                    "updated_at",
                ]
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="legacy_material.submission.verify",
                    resource_type="legacy_material_submission",
                    resource_public_id=submission.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=timezone.now(),
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "processing_status": submission.processing_status,
                        "verified_by_public_id": str(actor.public_id),
                        "note": submission.verification_note,
                    },
                )
            )
        return submission


@dataclass(frozen=True)
class CreateLegacyMaterialVersionChain:
    context: CommandContext
    ordered_submission_ids: Sequence[UUID]
    current_submission_id: UUID
    owner: MaterialOwner
    material_type_code: str

    def execute(self) -> list[ProductMaterial]:
        actor = self.context.actor
        if not self.ordered_submission_ids:
            raise MaterialChainRejected("A chain needs at least one submission.")
        if self.current_submission_id not in set(self.ordered_submission_ids):
            raise MaterialChainRejected(
                "The current version must be one of the submissions in the chain."
            )

        with transaction.atomic():
            submissions = self._locked_submissions(actor.organization_id)
            # Re-authorize against the locked submissions' real sensitivity so a
            # stale pre-lock grant cannot promote a higher-sensitivity file.
            for submission in submissions:
                _require(
                    actor,
                    action="product_material.manage",
                    resource_type="product_material",
                    public_id=None,
                    organization_id=actor.organization_id,
                    sensitivity_level=submission.document_version.sensitivity_level,
                )
            previous, next_version = self._chain_tail(actor.organization_id)
            created: list[ProductMaterial] = []
            current: ProductMaterial | None = None

            for submission in submissions:
                is_current = submission.public_id == self.current_submission_id
                document_version = submission.document_version
                material = ProductMaterial.objects.create(
                    organization_id=actor.organization_id,
                    owner_type=self.owner.owner_type,
                    owner_id=self.owner.owner_id,
                    material_type_code=self.material_type_code,
                    document_version=document_version,
                    # Inherit the controlled file's sensitivity so later confirm
                    # and download checks cannot silently downgrade HIGHLY_SENSITIVE.
                    sensitivity_level=document_version.sensitivity_level,
                    material_status=(
                        MaterialStatus.DRAFT if is_current else MaterialStatus.INACTIVE
                    ),
                    version_no=next_version,
                    supersedes_material=previous,
                    source_submission=submission,
                )
                submission.promoted_material = material
                submission.save(update_fields=["promoted_material", "updated_at"])
                append_event(
                    AuditRecord(
                        actor=actor,
                        action_code="product_material.promote",
                        resource_type="product_material",
                        resource_public_id=material.public_id,
                        result=AuditResult.SUCCESS,
                        trace_id=self.context.trace_id,
                        occurred_at=timezone.now(),
                        acting_roles_snapshot=acting_roles_snapshot(actor),
                        after_summary=self._audit_summary(material, submission),
                    )
                )
                created.append(material)
                if is_current:
                    current = material
                previous = material
                next_version += 1

            assert current is not None  # the caller's nomination was validated above
            make_material_current(current)

        return created

    def _locked_submissions(self, organization_id: int) -> list[LegacyMaterialSubmission]:
        found = {
            submission.public_id: submission
            for submission in LegacyMaterialSubmission.objects.select_for_update()
            .select_related("document_version")
            .filter(
                public_id__in=list(self.ordered_submission_ids),
                organization_id=organization_id,
            )
        }
        ordered: list[LegacyMaterialSubmission] = []
        for public_id in self.ordered_submission_ids:
            submission = found.get(public_id)
            if submission is None:
                raise MaterialChainRejected(f"Submission {public_id} does not exist.")
            if submission.processing_status != LegacyMaterialStatus.VERIFIED:
                raise MaterialChainRejected(
                    f"Submission {public_id} is {submission.processing_status}; only a "
                    "verified submission may become a product material."
                )
            if submission.verified_by_id is None:
                # A status set outside the verification service leaves nobody
                # accountable for the provenance, so it does not count.
                raise MaterialChainRejected(
                    f"Submission {public_id} carries no verifier and cannot be promoted."
                )
            if submission.promoted_material_id is not None:
                raise MaterialChainRejected(
                    f"Submission {public_id} is already part of a material chain."
                )
            ordered.append(submission)
        return ordered

    def _chain_tail(self, organization_id: int) -> tuple[ProductMaterial | None, int]:
        existing = (
            ProductMaterial.objects.select_for_update()
            .filter(
                organization_id=organization_id,
                owner_type=self.owner.owner_type,
                owner_id=self.owner.owner_id,
                material_type_code=self.material_type_code,
            )
            .order_by("version_no")
        )
        tail = existing.last()
        highest = existing.aggregate(highest=Max("version_no"))["highest"] or 0
        return tail, highest + 1

    def _audit_summary(
        self, material: ProductMaterial, submission: LegacyMaterialSubmission
    ) -> dict[str, Any]:
        return {
            "owner_type": material.owner_type,
            "owner_id": material.owner_id,
            "material_type_code": material.material_type_code,
            "version_no": material.version_no,
            "source_submission_public_id": str(submission.public_id),
            "document_version_public_id": str(material.document_version.public_id),
        }


def _require(
    actor: Any,
    *,
    action: str,
    resource_type: str,
    public_id: UUID | None,
    organization_id: int,
    sensitivity_level: str = "INTERNAL",
) -> None:
    decision = authorize(
        subject_for(actor),
        action=action,
        resource=ResourceDescriptor(
            resource_type=resource_type,
            public_id=public_id,
            organization_id=organization_id,
            sensitivity_level=sensitivity_level,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()
