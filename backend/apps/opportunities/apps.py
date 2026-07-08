"""Opportunity, proposal, candidate and quota domain."""

from __future__ import annotations

from django.apps import AppConfig


class OpportunitiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.opportunities"
    label = "opportunities"
