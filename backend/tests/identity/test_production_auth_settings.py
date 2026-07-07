"""Production settings must reject development-only authentication."""

from __future__ import annotations

import importlib

import pytest
from django.core.exceptions import ImproperlyConfigured


def test_production_settings_reject_dev_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DJANGO_SECRET_KEY", "prod-secret")
    monkeypatch.setenv("DJANGO_ALLOWED_HOSTS", "example.com")
    monkeypatch.setenv("MYSQL_DATABASE", "meridian")
    monkeypatch.setenv("MYSQL_USER", "meridian")
    monkeypatch.setenv("MYSQL_PASSWORD", "secret")
    monkeypatch.setenv("MYSQL_HOST", "db")
    monkeypatch.setenv("ENABLE_DEV_LOGIN", "true")

    with pytest.raises(ImproperlyConfigured, match="ENABLE_DEV_LOGIN"):
        importlib.reload(importlib.import_module("config.settings.production"))
