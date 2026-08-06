"""Judge product material completeness against a pinned requirements version.

The requirements configuration says which material types a product category
must carry in a given lifecycle state. This module answers, for one business
object, what is satisfied, what is missing, what is waiting on a professional
and what is still sitting in the triage queue — and names the exact
configuration version it read, so the answer stays reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db.models import TextChoices

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import PRODUCT_MATERIAL_REQUIREMENTS_CODE
from apps.identity.models.organization import Organization
from apps.products.models import (
    LegacyMaterialStatus,
    LegacyMaterialSubmission,
    MaterialStatus,
    ProductMaterial,
)

REQUIRED = "REQUIRED"
OPTIONAL = "OPTIONAL"
NOT_APPLICABLE = "NOT_APPLICABLE"


class MaterialRequirementsUnavailable(Exception):
    """No published requirements version exists to judge against."""


class MaterialCompletenessState(TextChoices):
    SATISFIED = "SATISFIED", "Satisfied"
    MISSING = "MISSING", "Missing"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION", "Pending confirmation"
    PENDING_TRIAGE = "PENDING_TRIAGE", "Pending triage"
    NOT_APPLICABLE = "NOT_APPLICABLE", "Not applicable"


@dataclass(frozen=True)
class MaterialCompletenessItem:
    material_type_code: str
    requirement: str
    state: str


@dataclass(frozen=True)
class MaterialCompletenessResult:
    requirement_version_public_id: UUID
    requirement_version_number: int
    requirement_content_digest: str
    items: tuple[MaterialCompletenessItem, ...]

    @property
    def blocking_material_type_codes(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                item.material_type_code
                for item in self.items
                if item.requirement == REQUIRED
                and item.state != MaterialCompletenessState.SATISFIED
            )
        )

    @property
    def is_complete(self) -> bool:
        return not self.blocking_material_type_codes


def published_requirements(organization: Organization) -> ConfigurationVersion:
    definition = ConfigurationDefinition.objects.filter(
        organization=organization,
        definition_code=PRODUCT_MATERIAL_REQUIREMENTS_CODE,
    ).first()
    if definition is None:
        raise MaterialRequirementsUnavailable("No product material requirements are defined.")

    version = (
        ConfigurationVersion.objects.filter(
            definition=definition,
            status=ConfigurationStatus.PUBLISHED,
        )
        .order_by("-version_number")
        .first()
    )
    if version is None:
        raise MaterialRequirementsUnavailable("No product material requirements are published.")
    return version


def evaluate_material_completeness(
    *,
    organization: Organization,
    owner_type: str,
    owner_id: int,
    product_category_code: str,
    lifecycle_state: str,
    requirement_version: ConfigurationVersion | None = None,
) -> MaterialCompletenessResult:
    """Evaluate one business object against the requirements.

    Pass `requirement_version` to re-read a decision that was already made; omit
    it to read whichever version is published right now.
    """

    version = requirement_version or published_requirements(organization)
    required_materials = _materials_for(
        version.content_json,
        product_category_code=product_category_code,
        lifecycle_state=lifecycle_state,
    )

    current_materials = {
        material.material_type_code: material
        for material in ProductMaterial.objects.filter(
            organization=organization,
            owner_type=owner_type,
            owner_id=owner_id,
            current_slot=1,
        )
    }
    triaged = set(
        LegacyMaterialSubmission.objects.filter(
            organization=organization,
            owner_type=owner_type,
            owner_id=owner_id,
            processing_status=LegacyMaterialStatus.PENDING_TRIAGE,
        ).values_list("document_version__catalog_item_code", flat=True)
    )

    items = tuple(
        MaterialCompletenessItem(
            material_type_code=entry["material_type_code"],
            requirement=entry["requirement"],
            state=_state_for(
                requirement=entry["requirement"],
                material=current_materials.get(entry["material_type_code"]),
                has_triage_item=entry["material_type_code"] in triaged,
            ),
        )
        for entry in required_materials
    )

    return MaterialCompletenessResult(
        requirement_version_public_id=version.public_id,
        requirement_version_number=version.version_number,
        requirement_content_digest=version.content_digest,
        items=items,
    )


def _materials_for(
    content: dict[str, Any], *, product_category_code: str, lifecycle_state: str
) -> list[dict[str, str]]:
    for requirement in content.get("requirements", []):
        if (
            requirement.get("product_category_code") == product_category_code
            and requirement.get("lifecycle_state") == lifecycle_state
        ):
            return list(requirement.get("materials", []))
    return []


def _state_for(*, requirement: str, material: ProductMaterial | None, has_triage_item: bool) -> str:
    if requirement == NOT_APPLICABLE:
        return MaterialCompletenessState.NOT_APPLICABLE
    if material is None:
        # A queued file is visible progress, but it is not a material yet.
        if has_triage_item:
            return MaterialCompletenessState.PENDING_TRIAGE
        return MaterialCompletenessState.MISSING
    if material.material_status == MaterialStatus.APPROVED:
        return MaterialCompletenessState.SATISFIED
    return MaterialCompletenessState.PENDING_CONFIRMATION
