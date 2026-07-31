"""Completeness is judged against one pinned requirements version.

A pre-check that silently follows configuration changes is not evidence. Every
evaluation therefore names the requirements version it read, and callers store
that identifier alongside the decision they made from it.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.utils import timezone

from apps.configuration.models import (
    ConfigurationDefinition,
    ConfigurationStatus,
    ConfigurationVersion,
)
from apps.configuration.schema_registry import PRODUCT_MATERIAL_REQUIREMENTS_CODE
from apps.products.models import (
    AttributeOwnerType,
    LegacyMaterialStatus,
    LegacyMaterialSubmission,
    MaterialStatus,
    ProductMaterial,
)
from apps.products.services.material_requirements import (
    MaterialCompletenessState,
    MaterialRequirementsUnavailable,
    evaluate_material_completeness,
)

pytestmark = pytest.mark.django_db

CATEGORY = "YOGURT"
LIFECYCLE = "ON_SALE"
OWNER_ID = 771


@pytest.fixture
def requirements(organization, active_user) -> Any:
    definition, _ = ConfigurationDefinition.objects.get_or_create(
        organization=organization,
        definition_code=PRODUCT_MATERIAL_REQUIREMENTS_CODE,
        defaults={"name": "产品材料要求", "description": ""},
    )
    counter = {"version": 0}

    def _publish(materials: list[dict[str, str]]) -> ConfigurationVersion:
        ConfigurationVersion.objects.filter(
            definition=definition, status=ConfigurationStatus.PUBLISHED
        ).update(status=ConfigurationStatus.RETIRED, current_published_slot=None)
        counter["version"] += 1
        return ConfigurationVersion.objects.create(
            organization=organization,
            definition=definition,
            version_number=counter["version"],
            status=ConfigurationStatus.PUBLISHED,
            current_published_slot=1,
            content_json={
                "requirements": [
                    {
                        "product_category_code": CATEGORY,
                        "lifecycle_state": LIFECYCLE,
                        "materials": materials,
                    }
                ]
            },
            created_by=active_user,
            published_at=timezone.now(),
        )

    return _publish


@pytest.fixture
def material(organization, change_set, controlled_document_version) -> Any:
    def _create(
        material_type_code: str,
        *,
        status: str = MaterialStatus.APPROVED,
        version_no: int = 1,
        current: bool = True,
    ) -> ProductMaterial:
        return ProductMaterial.objects.create(
            organization=organization,
            change_set=change_set,
            owner_type=AttributeOwnerType.PRODUCT,
            owner_id=OWNER_ID,
            material_type_code=material_type_code,
            document_version=controlled_document_version(code=material_type_code),
            material_status=status,
            version_no=version_no,
            current_slot=1 if current else None,
        )

    return _create


def evaluate(organization) -> Any:
    return evaluate_material_completeness(
        organization=organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=OWNER_ID,
        product_category_code=CATEGORY,
        lifecycle_state=LIFECYCLE,
    )


def states(result) -> dict[str, str]:
    return {item.material_type_code: item.state for item in result.items}


def test_a_required_material_that_was_never_uploaded_is_missing(organization, requirements) -> None:
    requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])

    result = evaluate(organization)

    assert states(result) == {"PRODUCT_LABEL": MaterialCompletenessState.MISSING}
    assert result.blocking_material_type_codes == ("PRODUCT_LABEL",)
    assert result.is_complete is False


def test_a_required_material_awaiting_confirmation_still_blocks(
    organization, requirements, material
) -> None:
    requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])
    material("PRODUCT_LABEL", status=MaterialStatus.DRAFT)

    result = evaluate(organization)

    assert states(result) == {"PRODUCT_LABEL": MaterialCompletenessState.PENDING_CONFIRMATION}
    assert result.blocking_material_type_codes == ("PRODUCT_LABEL",)


def test_a_confirmed_current_material_satisfies_the_requirement(
    organization, requirements, material
) -> None:
    requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])
    material("PRODUCT_LABEL", status=MaterialStatus.APPROVED)

    result = evaluate(organization)

    assert states(result) == {"PRODUCT_LABEL": MaterialCompletenessState.SATISFIED}
    assert result.is_complete is True


def test_an_approved_but_superseded_material_does_not_satisfy_the_requirement(
    organization, requirements, material
) -> None:
    requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])
    material("PRODUCT_LABEL", status=MaterialStatus.APPROVED, current=False)

    result = evaluate(organization)

    assert states(result) == {"PRODUCT_LABEL": MaterialCompletenessState.MISSING}


def test_a_file_still_in_the_triage_queue_is_reported_but_does_not_count(
    organization, requirements, controlled_document_version, active_user
) -> None:
    requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])
    LegacyMaterialSubmission.objects.create(
        organization=organization,
        document_version=controlled_document_version(code="PRODUCT_LABEL"),
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=OWNER_ID,
        submitted_by=active_user,
        sha256="c" * 64,
        idempotency_key="triage-1",
        processing_status=LegacyMaterialStatus.PENDING_TRIAGE,
    )

    result = evaluate(organization)

    assert states(result) == {"PRODUCT_LABEL": MaterialCompletenessState.PENDING_TRIAGE}
    assert result.blocking_material_type_codes == ("PRODUCT_LABEL",)


def test_an_optional_material_never_blocks_even_when_absent(organization, requirements) -> None:
    requirements(
        [
            {"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"},
            {"material_type_code": "MARKETING_IMAGE", "requirement": "OPTIONAL"},
        ]
    )

    result = evaluate(organization)

    assert states(result)["MARKETING_IMAGE"] == MaterialCompletenessState.MISSING
    assert result.blocking_material_type_codes == ("PRODUCT_LABEL",)


def test_a_not_applicable_material_is_listed_separately_and_never_blocks(
    organization, requirements
) -> None:
    requirements([{"material_type_code": "EXPORT_CERTIFICATE", "requirement": "NOT_APPLICABLE"}])

    result = evaluate(organization)

    assert states(result) == {"EXPORT_CERTIFICATE": MaterialCompletenessState.NOT_APPLICABLE}
    assert result.blocking_material_type_codes == ()
    assert result.is_complete is True


def test_the_result_pins_the_requirements_version_it_read(organization, requirements) -> None:
    published = requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])

    result = evaluate(organization)

    assert result.requirement_version_public_id == published.public_id
    assert result.requirement_content_digest == published.content_digest
    assert result.requirement_version_number == published.version_number


def test_a_later_publish_does_not_rewrite_an_earlier_evaluation(organization, requirements) -> None:
    first = requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])
    before = evaluate(organization)

    requirements(
        [
            {"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"},
            {"material_type_code": "EXPORT_CERTIFICATE", "requirement": "REQUIRED"},
        ]
    )
    after = evaluate(organization)

    assert before.requirement_version_public_id == first.public_id
    assert before.blocking_material_type_codes == ("PRODUCT_LABEL",)
    assert after.blocking_material_type_codes == ("EXPORT_CERTIFICATE", "PRODUCT_LABEL")


def test_a_category_without_requirements_yields_nothing_to_check(
    organization, requirements
) -> None:
    requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])

    result = evaluate_material_completeness(
        organization=organization,
        owner_type=AttributeOwnerType.PRODUCT,
        owner_id=OWNER_ID,
        product_category_code="UNLISTED_CATEGORY",
        lifecycle_state=LIFECYCLE,
    )

    assert result.items == ()
    assert result.is_complete is True


def test_evaluation_refuses_to_guess_when_no_requirements_are_published(
    organization,
) -> None:
    with pytest.raises(MaterialRequirementsUnavailable):
        evaluate(organization)


def test_a_draft_requirements_version_is_ignored(organization, requirements, active_user) -> None:
    published = requirements([{"material_type_code": "PRODUCT_LABEL", "requirement": "REQUIRED"}])
    ConfigurationVersion.objects.create(
        organization=organization,
        definition=published.definition,
        version_number=published.version_number + 1,
        status=ConfigurationStatus.DRAFT,
        content_json={
            "requirements": [
                {
                    "product_category_code": CATEGORY,
                    "lifecycle_state": LIFECYCLE,
                    "materials": [
                        {"material_type_code": "EXPORT_CERTIFICATE", "requirement": "REQUIRED"}
                    ],
                }
            ]
        },
        created_by=active_user,
    )

    result = evaluate(organization)

    assert states(result) == {"PRODUCT_LABEL": MaterialCompletenessState.MISSING}
