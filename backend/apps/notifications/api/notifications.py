"""In-app notification list and recipient lifecycle actions."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.notifications.models import (
    Notification,
    NotificationCategory,
    NotificationLevel,
    NotificationStatus,
)
from apps.notifications.queries.notifications import list_my_notifications
from apps.notifications.services.lifecycle import CloseNotification, MarkNotificationRead
from apps.platform.api.errors import ValidationFailedError
from apps.platform.api.permissions import requires_action
from apps.platform.application.command import CommandContext

NotificationReadPermission = requires_action(
    action_code="notification.message.read",
    resource_type="notification.message",
)
NotificationMarkReadPermission = requires_action(
    action_code="notification.message.mark_read",
    resource_type="notification.message",
)
NotificationClosePermission = requires_action(
    action_code="notification.message.close",
    resource_type="notification.message",
)


def _notification_item_fields() -> dict[str, serializers.Field]:
    return {
        "public_id": serializers.UUIDField(),
        "summary": serializers.CharField(),
        "category": serializers.CharField(allow_blank=True),
        "level": serializers.CharField(allow_blank=True),
        "status": serializers.CharField(),
        "deep_link": serializers.CharField(),
        "created_at": serializers.DateTimeField(),
        "read_at": serializers.DateTimeField(allow_null=True),
        "closed_at": serializers.DateTimeField(allow_null=True),
        "close_reason": serializers.CharField(allow_blank=True),
    }


def _serialize(notification: Notification) -> dict[str, Any]:
    return {
        "public_id": str(notification.public_id),
        "summary": notification.summary,
        "category": notification.category,
        "level": notification.level,
        "status": notification.status,
        "deep_link": notification.deep_link,
        "created_at": notification.created_at.isoformat(),
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "closed_at": notification.closed_at.isoformat() if notification.closed_at else None,
        "close_reason": notification.close_reason,
    }


def _parse_page(raw: str | None, *, default: int) -> int:
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationFailedError(message="page and page_size must be integers.") from exc


class MyNotificationsView(APIView):
    permission_classes = [IsAuthenticated, NotificationReadPermission]

    @extend_schema(
        operation_id="notifications_my_list",
        parameters=[
            OpenApiParameter(name="status", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="category", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="level", type=str, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="page", type=int, location=OpenApiParameter.QUERY),
            OpenApiParameter(name="page_size", type=int, location=OpenApiParameter.QUERY),
        ],
        responses=inline_serializer(
            name="MyNotificationPage",
            fields={
                "items": serializers.ListField(
                    child=inline_serializer(
                        name="MyNotificationItem", fields=_notification_item_fields()
                    )
                ),
                "page": serializers.IntegerField(),
                "page_size": serializers.IntegerField(),
                "count": serializers.IntegerField(),
                "unread_count": serializers.IntegerField(),
            },
        ),
    )
    def get(self, request: Request) -> Response:
        user = cast(User, request.user)
        status = request.query_params.get("status")
        category = request.query_params.get("category")
        level = request.query_params.get("level")
        if status and status not in NotificationStatus.values:
            raise ValidationFailedError(details={"status": ["Invalid status filter."]})
        if category and category not in NotificationCategory.values:
            raise ValidationFailedError(details={"category": ["Invalid category filter."]})
        if level and level not in NotificationLevel.values:
            raise ValidationFailedError(details={"level": ["Invalid level filter."]})

        page = list_my_notifications(
            user=user,
            status=status or None,
            category=category or None,
            level=level or None,
            page=_parse_page(request.query_params.get("page"), default=1),
            page_size=_parse_page(request.query_params.get("page_size"), default=20),
        )
        return Response(
            {
                "items": [_serialize(item) for item in page.items],
                "page": page.page,
                "page_size": page.page_size,
                "count": page.count,
                "unread_count": page.unread_count,
            }
        )


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated, NotificationMarkReadPermission]

    @extend_schema(
        operation_id="notifications_mark_read",
        request=None,
        responses={
            200: inline_serializer(
                name="NotificationReadResult", fields=_notification_item_fields()
            )
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        notification = MarkNotificationRead(
            context=CommandContext.for_actor(user),
            notification_public_id=public_id,
        ).execute()
        return Response(_serialize(notification))


class NotificationCloseView(APIView):
    permission_classes = [IsAuthenticated, NotificationClosePermission]

    @extend_schema(
        operation_id="notifications_close",
        request=inline_serializer(
            name="NotificationCloseRequest",
            fields={"close_reason": serializers.CharField(required=False, allow_blank=True)},
        ),
        responses={
            200: inline_serializer(
                name="NotificationCloseResult", fields=_notification_item_fields()
            )
        },
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        notification = CloseNotification(
            context=CommandContext.for_actor(user),
            notification_public_id=public_id,
            close_reason=str(request.data.get("close_reason") or ""),
        ).execute()
        return Response(_serialize(notification))
