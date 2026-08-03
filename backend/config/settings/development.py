"""Development settings: local, insecure defaults for host-run application."""

from __future__ import annotations

from .base import *  # noqa: F403
from .base import DATABASES, env, env_list

DEBUG = True

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-secret-key-do-not-use-in-production")

# Loopback defaults plus any explicit pilot LAN hosts from the environment.
# start-pilot.ps1 sets DJANGO_ALLOWED_HOSTS / DJANGO_CSRF_TRUSTED_ORIGINS.
ALLOWED_HOSTS = list(
    dict.fromkeys(
        ["localhost", "127.0.0.1", "[::1]", *env_list("DJANGO_ALLOWED_HOSTS")]
    )
)

CSRF_TRUSTED_ORIGINS = list(
    dict.fromkeys(
        [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://[::1]:5173",
            *env_list("DJANGO_CSRF_TRUSTED_ORIGINS"),
        ]
    )
)

DATABASES["default"]["NAME"] = env("MYSQL_DATABASE", "meridian")
DATABASES["default"]["USER"] = env("MYSQL_USER", "meridian")
DATABASES["default"]["PASSWORD"] = env("MYSQL_PASSWORD", "meridian")
DATABASES["default"]["HOST"] = env("MYSQL_HOST", "127.0.0.1")
DATABASES["default"]["PORT"] = env("MYSQL_PORT", "3306")

ENABLE_IDENTITY_API = True
ENABLE_DEV_LOGIN = True
ENABLE_AUTHORIZATION_API = True
ENABLE_AUDIT_API = True
ENABLE_CONFIGURATION_API = True
ENABLE_DOCUMENTS_API = True
ENABLE_NOTIFICATIONS_API = True
ENABLE_OPPORTUNITIES_API = True
ENABLE_STAGE_GATES_API = True
ENABLE_PROJECTS_API = True
ENABLE_WORK_ITEMS_API = True
ENABLE_PRODUCTS_API = True
ENABLE_OPERATIONS_API = True
# Phase 6: in-app only. An unset DINGTALK_NOTIFIER is not a decision; this is.
ENABLE_DINGTALK_NOTIFICATIONS = False
ENABLE_PILOT_PASSWORD_LOGIN = True

FILE_STORAGE_ROOT = BASE_DIR / "var" / "files"  # noqa: F405

from apps.integrations.dingtalk.fake_gateway import FakeDingTalkGateway  # noqa: E402

DINGTALK_GATEWAY = FakeDingTalkGateway()
