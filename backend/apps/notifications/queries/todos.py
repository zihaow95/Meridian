"""Query helpers for authoritative todos."""

from __future__ import annotations

from django.db.models import QuerySet

from apps.identity.models.user import User
from apps.notifications.models import Todo


def list_my_todos(*, user: User, status: str | None = None) -> QuerySet[Todo]:
    queryset = Todo.objects.filter(assignee=user).order_by("-created_at")
    if status:
        queryset = queryset.filter(status=status)
    return queryset
