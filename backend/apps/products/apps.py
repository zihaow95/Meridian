"""Minimal product asset shell for phase 2 project creation."""

from __future__ import annotations

from django.apps import AppConfig


class ProductsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.products"
    label = "products"

    def ready(self) -> None:
        from apps.products.policies import register_providers

        register_providers()
