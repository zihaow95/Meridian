"""Notification API routes."""

from __future__ import annotations

from django.urls import path

from apps.notifications.api.notifications import (
    MyNotificationsView,
    NotificationCloseView,
    NotificationReadView,
)
from apps.notifications.api.todos import MyTodosView

urlpatterns = [
    path("todos/my", MyTodosView.as_view(), name="todos-my"),
    path("notifications/my", MyNotificationsView.as_view(), name="notifications-my"),
    path(
        "notifications/<uuid:public_id>/read",
        NotificationReadView.as_view(),
        name="notifications-read",
    ),
    path(
        "notifications/<uuid:public_id>/close",
        NotificationCloseView.as_view(),
        name="notifications-close",
    ),
]
