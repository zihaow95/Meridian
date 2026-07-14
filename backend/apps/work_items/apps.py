from __future__ import annotations

from django.apps import AppConfig


class WorkItemsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.work_items"
    label = "work_items"

    def ready(self) -> None:
        from apps.work_items.policies import register_providers

        register_providers()
