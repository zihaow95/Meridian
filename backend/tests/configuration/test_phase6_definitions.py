"""Phase 6 governs controlled files and notifications through published configuration.

The technical file catalog belongs to the platform administrator and the product
material requirements belong to the product director, so the two are separate
definitions rather than one file policy. Notification classification lives in
configuration as well, so categories and levels can change without forking rules
across modules.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.authorization.models.admin_change import AdminChangeStatus
from apps.configuration.models import ConfigurationDefinition, ConfigurationStatus
from apps.configuration.schema_registry import (
    NOTIFICATION_CATEGORIES,
    NOTIFICATION_DELIVERY_POLICY_CODE,
    NOTIFICATION_LEVELS,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
    PRODUCT_MATERIAL_REQUIREMENTS_CODE,
    SENSITIVITY_LEVELS,
    TECHNICAL_FILE_CATALOG_CODE,
    get_schema,
    validate_content,
)
from apps.configuration.services import (
    CreateDraft,
    PublishVersion,
    RequestConfigurationPublication,
    ReviewConfigurationPublication,
)
from apps.platform.application.command import CommandContext

PHASE6_DEFINITION_CODES = [
    TECHNICAL_FILE_CATALOG_CODE,
    PRODUCT_MATERIAL_REQUIREMENTS_CODE,
    NOTIFICATION_TEMPLATE_CATALOG_CODE,
    NOTIFICATION_DELIVERY_POLICY_CODE,
]


def technical_file_catalog() -> dict[str, Any]:
    return {
        "catalog_items": [
            {
                "item_code": "PRODUCT_SPEC",
                "name": "Product specification",
                "allowed_mime_types": ["application/pdf"],
                "max_bytes": 52_428_800,
                "preview_enabled": True,
                "default_sensitivity_level": "SENSITIVE_CONTROLLED",
                "retention_years": 5,
            }
        ]
    }


def product_material_requirements() -> dict[str, Any]:
    return {
        "requirements": [
            {
                "product_category_code": "FOOD",
                "lifecycle_state": "ON_MARKET",
                "materials": [
                    {"material_type_code": "PRODUCT_SPEC", "requirement": "REQUIRED"},
                    {"material_type_code": "DESIGN_SOURCE", "requirement": "OPTIONAL"},
                    {"material_type_code": "CHANNEL_IMAGE", "requirement": "NOT_APPLICABLE"},
                ],
            }
        ]
    }


def notification_template_catalog() -> dict[str, Any]:
    return {
        "templates": [
            {
                "template_code": "MATERIAL_CONFIRMATION_REQUESTED",
                "category": "ACTION_REQUIRED",
                "default_level": "IMPORTANT",
                "summary_template": "{product_name} awaits {material_type} confirmation",
                "allowed_variables": ["product_name", "material_type"],
            }
        ]
    }


def notification_delivery_policy() -> dict[str, Any]:
    return {
        "rules": [
            {"category": category, "level": level, "channels": ["IN_APP"]}
            for category in NOTIFICATION_CATEGORIES
            for level in NOTIFICATION_LEVELS
        ]
    }


CONTENT_BY_CODE = {
    TECHNICAL_FILE_CATALOG_CODE: technical_file_catalog,
    PRODUCT_MATERIAL_REQUIREMENTS_CODE: product_material_requirements,
    NOTIFICATION_TEMPLATE_CATALOG_CODE: notification_template_catalog,
    NOTIFICATION_DELIVERY_POLICY_CODE: notification_delivery_policy,
}


@pytest.mark.parametrize("definition_code", PHASE6_DEFINITION_CODES)
def test_phase6_definition_has_a_registered_schema(definition_code: str) -> None:
    assert get_schema(definition_code) is not None


@pytest.mark.parametrize("definition_code", PHASE6_DEFINITION_CODES)
def test_phase6_reference_content_passes_validation(definition_code: str) -> None:
    assert validate_content(definition_code, CONTENT_BY_CODE[definition_code]()) == []


@pytest.mark.django_db
@pytest.mark.parametrize("definition_code", PHASE6_DEFINITION_CODES)
def test_phase6_definition_can_be_drafted_and_published_under_dual_control(
    definition_code: str, organization, active_user, another_active_user, grant_action
) -> None:
    grant_action(active_user, "configuration.publication.request", "configuration.version")
    grant_action(another_active_user, "configuration.publication.review", "configuration.version")
    definition = ConfigurationDefinition.objects.create(
        organization=organization,
        definition_code=definition_code,
        name=definition_code,
    )

    draft = CreateDraft(
        actor=active_user,
        definition=definition,
        content=CONTENT_BY_CODE[definition_code](),
    ).execute()
    request = RequestConfigurationPublication(
        context=CommandContext.for_actor(active_user),
        version_public_id=draft.public_id,
    ).execute()
    approved = ReviewConfigurationPublication(
        context=CommandContext.for_actor(another_active_user),
        request_public_id=request.public_id,
        decision=AdminChangeStatus.APPROVED,
    ).execute()
    published = PublishVersion(
        version=draft, actor=active_user, approved_request=approved
    ).execute()

    assert published.status == ConfigurationStatus.PUBLISHED
    assert published.current_published_slot == 1


def test_catalog_item_rejects_an_unknown_sensitivity_level() -> None:
    content = technical_file_catalog()
    content["catalog_items"][0]["default_sensitivity_level"] = "TOP_SECRET"

    assert validate_content(TECHNICAL_FILE_CATALOG_CODE, content) != []


def test_catalog_item_requires_an_explicit_size_limit() -> None:
    content = technical_file_catalog()
    del content["catalog_items"][0]["max_bytes"]

    assert validate_content(TECHNICAL_FILE_CATALOG_CODE, content) != []


def test_material_requirement_rejects_a_state_outside_the_three_allowed_ones() -> None:
    content = product_material_requirements()
    content["requirements"][0]["materials"][0]["requirement"] = "MAYBE"

    assert validate_content(PRODUCT_MATERIAL_REQUIREMENTS_CODE, content) != []


def test_notification_template_rejects_an_unknown_category() -> None:
    content = notification_template_catalog()
    content["templates"][0]["category"] = "GOSSIP"

    assert validate_content(NOTIFICATION_TEMPLATE_CATALOG_CODE, content) != []


def test_notification_template_rejects_an_unknown_level() -> None:
    content = notification_template_catalog()
    content["templates"][0]["default_level"] = "WHENEVER"

    assert validate_content(NOTIFICATION_TEMPLATE_CATALOG_CODE, content) != []


def test_delivery_policy_refuses_to_enable_dingtalk_in_phase_6() -> None:
    content = notification_delivery_policy()
    content["rules"][0]["channels"] = ["IN_APP", "DINGTALK"]

    assert validate_content(NOTIFICATION_DELIVERY_POLICY_CODE, content) != []


def test_catalog_rejects_duplicate_item_codes() -> None:
    content = technical_file_catalog()
    content["catalog_items"].append(dict(content["catalog_items"][0]))

    errors = validate_content(TECHNICAL_FILE_CATALOG_CODE, content)

    assert any("item_code" in error for error in errors)


def test_material_requirements_reject_duplicate_category_lifecycle_rows() -> None:
    content = product_material_requirements()
    content["requirements"].append(dict(content["requirements"][0]))

    errors = validate_content(PRODUCT_MATERIAL_REQUIREMENTS_CODE, content)

    assert any("product_category_code/lifecycle_state" in error for error in errors)


def test_material_requirements_reject_duplicate_material_type_codes_within_one_rule() -> None:
    content = product_material_requirements()
    content["requirements"][0]["materials"].append(dict(content["requirements"][0]["materials"][0]))

    errors = validate_content(PRODUCT_MATERIAL_REQUIREMENTS_CODE, content)

    assert errors != []
    assert any("material_type_code" in error for error in errors)


def test_notification_templates_reject_duplicate_template_codes() -> None:
    content = notification_template_catalog()
    content["templates"].append(dict(content["templates"][0]))

    errors = validate_content(NOTIFICATION_TEMPLATE_CATALOG_CODE, content)

    assert any("template_code" in error for error in errors)


def test_delivery_policy_rejects_duplicate_category_level_rules() -> None:
    content = notification_delivery_policy()
    content["rules"].append(dict(content["rules"][0]))

    errors = validate_content(NOTIFICATION_DELIVERY_POLICY_CODE, content)

    assert any("category/level" in error for error in errors)


def test_delivery_policy_rejects_a_missing_category_level_cell() -> None:
    content = notification_delivery_policy()
    content["rules"] = content["rules"][1:]

    errors = validate_content(NOTIFICATION_DELIVERY_POLICY_CODE, content)

    assert any("missing" in error for error in errors)


@pytest.mark.parametrize("definition_code", PHASE6_DEFINITION_CODES)
def test_phase6_definitions_reject_embedded_scripts_and_credentials(
    definition_code: str,
) -> None:
    content = CONTENT_BY_CODE[definition_code]()
    content["python"] = "import os"

    errors = validate_content(definition_code, content)

    assert any("python" in error for error in errors)


def test_catalog_sensitivity_levels_stay_in_sync_with_the_authorization_enum() -> None:
    """The schema literals cannot import the enum, so a drift here must fail loudly."""
    from apps.authorization.models.role import DataSensitivityLevel

    assert SENSITIVITY_LEVELS == list(DataSensitivityLevel.values)
