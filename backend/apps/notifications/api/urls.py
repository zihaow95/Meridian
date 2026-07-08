"""Notification API routes."""

from __future__ import annotations

from django.urls import path

from apps.notifications.api.todos import MyTodosView

urlpatterns = [
    path("todos/my", MyTodosView.as_view(), name="todos-my"),
]
