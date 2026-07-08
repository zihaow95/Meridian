"""Stable platform action codes for phase 1 APIs."""

from __future__ import annotations

from apps.authorization.models.role import ActionCategory

PLATFORM_ACTIONS: tuple[tuple[str, str, str], ...] = (
    ("identity.user.status_change", "identity.user", ActionCategory.ADMIN),
    ("authorization.role.read", "authorization.role", ActionCategory.READ),
    ("authorization.role.assign", "authorization.role", ActionCategory.ADMIN),
    (
        "authorization.admin_change.request",
        "authorization.admin_change_request",
        ActionCategory.ADMIN,
    ),
    (
        "authorization.admin_change.review",
        "authorization.admin_change_request",
        ActionCategory.ADMIN,
    ),
    (
        "authorization.troubleshoot.open",
        "authorization.troubleshoot_access",
        ActionCategory.ADMIN,
    ),
    ("audit.event.read", "audit.event", ActionCategory.READ),
    ("configuration.version.read", "configuration.version", ActionCategory.READ),
    ("configuration.version.publish", "configuration.version", ActionCategory.ADMIN),
    ("document.version.upload", "document.version", ActionCategory.WRITE),
    ("document.version.download", "document.version", ActionCategory.READ),
    ("notification.todo.read", "notification.todo", ActionCategory.READ),
)
