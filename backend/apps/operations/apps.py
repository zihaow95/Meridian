from __future__ import annotations

from django.apps import AppConfig


class OperationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.operations"
    label = "operations"

    def ready(self) -> None:
        from apps.operations.policies import register_providers

        register_providers()
