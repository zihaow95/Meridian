"""Root URL configuration.

Only infrastructure endpoints exist in phase 0; no business routes yet.
The interactive docs page is served only when DEBUG is enabled; the raw schema
endpoint is always available for contract tooling.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.platform.api.health import HealthView

urlpatterns = [
    path("api/v1/health", HealthView.as_view(), name="health"),
    path("api/v1/schema", SpectacularAPIView.as_view(), name="schema"),
]

if settings.DEBUG:
    urlpatterns += [
        path(
            "api/v1/docs",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]
