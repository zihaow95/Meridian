"""Identity API routes."""

from __future__ import annotations

from django.conf import settings
from django.urls import path

from apps.identity.api.auth import (
    AuthCapabilitiesView,
    CsrfView,
    DevLoginView,
    DingTalkCallbackView,
    DingTalkStartView,
    LogoutView,
    PilotLoginView,
)
from apps.identity.api.me import MeView

urlpatterns = [
    path("auth/csrf", CsrfView.as_view(), name="auth-csrf"),
    path("auth/capabilities", AuthCapabilitiesView.as_view(), name="auth-capabilities"),
    path("auth/dingtalk/start", DingTalkStartView.as_view(), name="auth-dingtalk-start"),
    path("auth/dingtalk/callback", DingTalkCallbackView.as_view(), name="auth-dingtalk-callback"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("me", MeView.as_view(), name="me"),
]

if getattr(settings, "ENABLE_DEV_LOGIN", False):
    urlpatterns.append(path("auth/dev/login", DevLoginView.as_view(), name="auth-dev-login"))

if getattr(settings, "ENABLE_PILOT_PASSWORD_LOGIN", False):
    urlpatterns.append(path("auth/pilot/login", PilotLoginView.as_view(), name="auth-pilot-login"))
