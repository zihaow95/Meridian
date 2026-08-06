"""Recipient-scoped notification queries."""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import QuerySet

from apps.identity.models.user import User
from apps.notifications.models import Notification, NotificationStatus

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


@dataclass(frozen=True)
class NotificationPage:
    items: list[Notification]
    page: int
    page_size: int
    count: int
    unread_count: int


def _recipient_queryset(user: User) -> QuerySet[Notification]:
    return Notification.objects.filter(
        recipient=user, organization_id=user.organization_id
    ).order_by("-created_at", "-id")


def unread_count_for(*, user: User) -> int:
    return _recipient_queryset(user).filter(status=NotificationStatus.UNREAD).count()


def list_my_notifications(
    *,
    user: User,
    status: str | None = None,
    category: str | None = None,
    level: str | None = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> NotificationPage:
    queryset = _recipient_queryset(user)
    if status:
        queryset = queryset.filter(status=status)
    if category:
        queryset = queryset.filter(category=category)
    if level:
        queryset = queryset.filter(level=level)

    page = max(page, 1)
    page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    count = queryset.count()
    start = (page - 1) * page_size
    return NotificationPage(
        items=list(queryset[start : start + page_size]),
        page=page,
        page_size=page_size,
        count=count,
        unread_count=unread_count_for(user=user),
    )
