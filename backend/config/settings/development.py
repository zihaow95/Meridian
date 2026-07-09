"""Development settings: local, insecure defaults for host-run application."""

from __future__ import annotations

from .base import *  # noqa: F403
from .base import DATABASES, env

DEBUG = True

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-secret-key-do-not-use-in-production")

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://[::1]:5173",
]

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
ENABLE_PRODUCTS_API = True

FILE_STORAGE_ROOT = BASE_DIR / "var" / "files"  # noqa: F405

from apps.integrations.dingtalk.fake_gateway import FakeDingTalkGateway  # noqa: E402

DINGTALK_GATEWAY = FakeDingTalkGateway()
