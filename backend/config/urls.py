"""Root URL configuration.

Only infrastructure endpoints exist in phase 0; no business routes yet.
"""

from __future__ import annotations

from django.urls import path

from apps.platform.api.health import HealthView

urlpatterns = [
    path("api/v1/health", HealthView.as_view(), name="health"),
]
