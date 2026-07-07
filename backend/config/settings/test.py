"""Test settings: run against the dedicated MySQL test database.

There is no SQLite fallback. The MySQL test database is provided by the local
Docker Compose stack (see deploy/compose/compose.dev.yml).
"""

from __future__ import annotations

from .base import *  # noqa: F403
from .base import DATABASES, env

DEBUG = False

SECRET_KEY = "test-insecure-secret-key"  # test-only, never deployed

ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]

DATABASES["default"]["NAME"] = env("MYSQL_DATABASE", "meridian")
DATABASES["default"]["USER"] = env("MYSQL_USER", "meridian")
DATABASES["default"]["PASSWORD"] = env("MYSQL_PASSWORD", "meridian")
DATABASES["default"]["HOST"] = env("MYSQL_HOST", "127.0.0.1")
DATABASES["default"]["PORT"] = env("MYSQL_PORT", "3306")
DATABASES["default"]["TEST"] = {
    "NAME": env("MYSQL_TEST_DATABASE", "meridian_test"),
    "CHARSET": "utf8mb4",
    "COLLATION": "utf8mb4_0900_ai_ci",
}

ENABLE_IDENTITY_API = True
ENABLE_DEV_LOGIN = True
ENABLE_AUTHORIZATION_API = True

from apps.integrations.dingtalk.fake_gateway import FakeDingTalkGateway  # noqa: E402

DINGTALK_GATEWAY = FakeDingTalkGateway()
