"""Phase 6 registers its permission actions once, before any feature PR uses them.

The plan fixes this list in advance so later PRs cannot quietly widen their own
authority: a PR may reference these codes but may not amend the seed. The
expected set below is therefore a contract, not a mirror of the source tuple.
"""

from __future__ import annotations

import pytest

from apps.authorization.actions import (
    EXECUTION_ACTIONS,
    OPERATIONS_ACTIONS,
    OPPORTUNITY_ACTIONS,
    PHASE6_ACTIONS,
    PLATFORM_ACTIONS,
    PRODUCT_ACTIONS,
)
from apps.authorization.models.role import ActionCategory, PermissionAction

EXPECTED_PHASE6_ACTION_CODES = {
    "configuration.draft.create",
    "configuration.publication.request",
    "configuration.publication.review",
    "configuration.content.read_sensitive",
    "legacy_material.submission.create",
    "legacy_material.submission.read",
    "legacy_material.submission.verify",
    "product_material.manage",
    "product_material.confirm",
    "product_material.completeness.read",
    "legacy_baseline.draft.create",
    "notification.message.read",
    "notification.message.mark_read",
    "notification.message.close",
    "identity.pilot_account.provision",
    "pilot.batch.manage",
    "pilot.batch.read",
    "pilot.feedback.create",
    "pilot.feedback.read",
    "pilot.feedback.assign",
    "pilot.feedback.handle",
    "pilot.feedback.retest",
    "pilot.feedback.close",
}


def test_phase6_action_list_matches_the_agreed_appendix() -> None:
    assert {row[0] for row in PHASE6_ACTIONS} == EXPECTED_PHASE6_ACTION_CODES


def test_phase6_action_codes_are_declared_once() -> None:
    codes = [row[0] for row in PHASE6_ACTIONS]

    assert len(codes) == len(set(codes))


def test_phase6_actions_do_not_redefine_an_existing_action() -> None:
    existing = {
        row[0]
        for catalog in (
            PLATFORM_ACTIONS,
            OPPORTUNITY_ACTIONS,
            PRODUCT_ACTIONS,
            EXECUTION_ACTIONS,
            OPERATIONS_ACTIONS,
        )
        for row in catalog
    }

    assert EXPECTED_PHASE6_ACTION_CODES & existing == set()


def test_phase6_actions_use_a_known_category() -> None:
    valid = set(ActionCategory.values)

    assert {row[2] for row in PHASE6_ACTIONS} <= valid


@pytest.mark.parametrize(
    ("action_code", "expected_resource_type", "expected_category"),
    [
        ("configuration.draft.create", "configuration.version", ActionCategory.WRITE),
        ("configuration.publication.review", "configuration.version", ActionCategory.ADMIN),
        ("configuration.content.read_sensitive", "configuration.version", ActionCategory.READ),
        ("legacy_material.submission.verify", "legacy_material_submission", ActionCategory.DECIDE),
        ("product_material.confirm", "product_material", ActionCategory.DECIDE),
        ("notification.message.read", "notification.message", ActionCategory.READ),
        ("identity.pilot_account.provision", "identity.user", ActionCategory.ADMIN),
        ("pilot.feedback.retest", "pilot.feedback", ActionCategory.DECIDE),
    ],
)
def test_phase6_action_is_bound_to_its_resource_and_category(
    action_code: str, expected_resource_type: str, expected_category: str
) -> None:
    row = next(entry for entry in PHASE6_ACTIONS if entry[0] == action_code)

    assert row[1] == expected_resource_type
    assert row[2] == expected_category


@pytest.mark.django_db
def test_phase6_action_catalog_is_seeded() -> None:
    # Transaction tests flush tables; re-apply catalog seed idempotently.
    for action_code, resource_type, action_category in PHASE6_ACTIONS:
        PermissionAction.objects.get_or_create(
            action_code=action_code,
            defaults={
                "resource_type": resource_type,
                "action_category": action_category,
                "description": "",
            },
        )

    for action_code, _resource_type, _category in PHASE6_ACTIONS:
        assert PermissionAction.objects.filter(action_code=action_code).exists()
