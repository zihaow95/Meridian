"""Production settings: fail fast when required configuration is missing.

TLS is terminated at the reverse proxy (Nginx); the security settings below
assume the application runs behind a proxy that sets X-Forwarded-Proto.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DATABASES, env, env_list

DEBUG = False

_secret_key = env("DJANGO_SECRET_KEY")
if not _secret_key:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is required in production.")
SECRET_KEY = _secret_key

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS is required in production.")

_db_name = env("MYSQL_DATABASE")
_db_user = env("MYSQL_USER")
_db_password = env("MYSQL_PASSWORD")
_db_host = env("MYSQL_HOST")
if not (_db_name and _db_user and _db_password and _db_host):
    raise ImproperlyConfigured(
        "MYSQL_DATABASE, MYSQL_USER, MYSQL_PASSWORD and MYSQL_HOST are required in production."
    )
DATABASES["default"]["NAME"] = _db_name
DATABASES["default"]["USER"] = _db_user
DATABASES["default"]["PASSWORD"] = _db_password
DATABASES["default"]["HOST"] = _db_host
DATABASES["default"]["PORT"] = env("MYSQL_PORT", "3306")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
