"""Query helpers for authoritative todos."""

from __future__ import annotations

from django.db.models import Prefetch, QuerySet

from apps.identity.models.user import User
from apps.notifications.models import Notification, Todo


def list_my_todos(*, user: User, status: str | None = None) -> QuerySet[Todo]:
    queryset = (
        Todo.objects.filter(assignee=user)
        .prefetch_related(
            Prefetch(
                "notifications",
                queryset=Notification.objects.order_by("-created_at"),
            )
        )
        .order_by("-created_at")
    )
    if status:
        queryset = queryset.filter(status=status)
    return queryset


def linked_notification(todo: Todo) -> Notification | None:
    notifications = list(todo.notifications.all())
    return notifications[0] if notifications else None
