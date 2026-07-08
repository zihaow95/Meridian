"""Opportunity, proposal, candidate and quota domain."""

from __future__ import annotations

from django.apps import AppConfig


class OpportunitiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.opportunities"
    label = "opportunities"

    def ready(self) -> None:
        from apps.opportunities.policies import identity_provider

        identity_provider.register_providers()
