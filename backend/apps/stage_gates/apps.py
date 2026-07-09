"""Major stage gate decisions shared across business domains."""

from __future__ import annotations

from django.apps import AppConfig


class StageGatesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.stage_gates"
    label = "stage_gates"
