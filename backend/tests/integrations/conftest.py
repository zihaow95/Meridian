"""Shared grants for integration tests that validate/publish configuration."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from apps.identity.models.user import User


@pytest.fixture(autouse=True)
def _grant_configuration_writer(active_user: User, grant_action: Callable[..., None]) -> None:
    grant_action(active_user, "configuration.draft.create", "configuration.version")
    grant_action(active_user, "configuration.version.read", "configuration.version")
    grant_action(active_user, "configuration.version.publish", "configuration.version")
