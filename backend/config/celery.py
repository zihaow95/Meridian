"""Celery application configuration."""

from __future__ import annotations

import os

from celery import Celery  # type: ignore[import-untyped]

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("meridian")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(["apps.platform.outbox"])
