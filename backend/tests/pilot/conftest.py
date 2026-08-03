"""Shared grants so pilot services re-authorize inside the transaction."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.identity.models.user import User


@pytest.fixture(autouse=True)
def _grant_pilot_write_actions(
    active_user: User, grant_action: Callable[..., None]
) -> None:
    for action, resource in (
        ("pilot.batch.manage", "pilot.batch"),
        ("pilot.batch.read", "pilot.batch"),
        ("pilot.feedback.create", "pilot.feedback"),
        ("pilot.feedback.read", "pilot.feedback"),
        ("pilot.feedback.assign", "pilot.feedback"),
        ("pilot.feedback.handle", "pilot.feedback"),
        ("pilot.feedback.retest", "pilot.feedback"),
        ("pilot.feedback.close", "pilot.feedback"),
        ("document.version.download", "document.version"),
    ):
        grant_action(active_user, action, resource)
