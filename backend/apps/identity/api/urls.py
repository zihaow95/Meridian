"""Identity API routes."""

from __future__ import annotations

from django.conf import settings
from django.urls import path

from apps.identity.api.auth import DevLoginView, DingTalkCallbackView, DingTalkStartView, LogoutView
from apps.identity.api.me import MeView

urlpatterns = [
    path("auth/dingtalk/start", DingTalkStartView.as_view(), name="auth-dingtalk-start"),
    path("auth/dingtalk/callback", DingTalkCallbackView.as_view(), name="auth-dingtalk-callback"),
    path("auth/logout", LogoutView.as_view(), name="auth-logout"),
    path("me", MeView.as_view(), name="me"),
]

if getattr(settings, "ENABLE_DEV_LOGIN", False):
    urlpatterns.append(path("auth/dev/login", DevLoginView.as_view(), name="auth-dev-login"))
