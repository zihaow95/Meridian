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


class PublicSchemaView(SpectacularAPIView):
    permission_classes = [AllowAny]


class PublicSwaggerView(SpectacularSwaggerView):
    permission_classes = [AllowAny]


urlpatterns: list[URLPattern | URLResolver] = [
    path("api/v1/health", HealthView.as_view(), name="health"),
    path("api/v1/schema", PublicSchemaView.as_view(), name="schema"),
]

if getattr(settings, "ENABLE_TEST_API", False):
    from apps.platform.api.test_views import HiddenResourceView

    urlpatterns += [
        path(
            "api/v1/_test/hidden-resource",
            HiddenResourceView.as_view(),
            name="hidden-resource-test",
        ),
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
    from apps.authorization.api.assignments import UserAssignmentsView
    from apps.authorization.api.grants import AuditEventsAdminView

    urlpatterns += [
        path("api/v1/authorization/roles", RoleCatalogView.as_view(), name="authorization-roles"),
        path(
            "api/v1/authorization/users/<uuid:public_id>/assignments",
            UserAssignmentsView.as_view(),
            name="authorization-user-assignments",
        ),
        path(
            "api/v1/admin/audit-events",
            AuditEventsAdminView.as_view(),
            name="admin-audit-events",
        ),
    ]

if getattr(settings, "ENABLE_AUDIT_API", False):
    from apps.audit.api.admin import AuditEventListView

    urlpatterns += [
        path("api/v1/audit/events", AuditEventListView.as_view(), name="audit-events"),
    ]

if getattr(settings, "ENABLE_NOTIFICATIONS_API", False):
    urlpatterns += [
        path("api/v1/", include("apps.notifications.api.urls")),
    ]

if getattr(settings, "ENABLE_CONFIGURATION_API", False):
    urlpatterns += [
        path("api/v1/", include("apps.configuration.api.urls")),
    ]

if getattr(settings, "ENABLE_DOCUMENTS_API", False):
    urlpatterns += [
        path("api/v1/", include("apps.documents.api.urls")),
    ]

if getattr(settings, "ENABLE_OPPORTUNITIES_API", False):
    urlpatterns += [
        path("api/v1/", include("apps.opportunities.api.urls")),
    ]

if getattr(settings, "ENABLE_STAGE_GATES_API", False):
    urlpatterns += [
        path("api/v1/", include("apps.stage_gates.api.urls")),
    ]
