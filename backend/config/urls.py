"""Root URL configuration.

Only infrastructure endpoints exist in phase 0; no business routes yet.
The interactive docs page is served only when DEBUG is enabled; the raw schema
endpoint is always available for contract tooling.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import URLPattern, URLResolver, include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.permissions import AllowAny

from apps.platform.api.health import HealthView
from apps.platform.api.test_views import HiddenResourceView


class PublicSchemaView(SpectacularAPIView):
    permission_classes = [AllowAny]


class PublicSwaggerView(SpectacularSwaggerView):
    permission_classes = [AllowAny]


urlpatterns: list[URLPattern | URLResolver] = [
    path("api/v1/health", HealthView.as_view(), name="health"),
    path("api/v1/schema", PublicSchemaView.as_view(), name="schema"),
    path("api/v1/_test/hidden-resource", HiddenResourceView.as_view(), name="hidden-resource-test"),
]

if settings.DEBUG:
    urlpatterns += [
        path(
            "api/v1/docs",
            PublicSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]

if getattr(settings, "ENABLE_IDENTITY_API", False):
    urlpatterns += [
        path("api/v1/", include("apps.identity.api.urls")),
    ]

if getattr(settings, "ENABLE_AUTHORIZATION_API", False):
    from apps.authorization.api.admin import RoleCatalogView

    urlpatterns += [
        path("api/v1/authorization/roles", RoleCatalogView.as_view(), name="authorization-roles"),
    ]
