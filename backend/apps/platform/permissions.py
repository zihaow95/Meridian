"""Default-deny permission classes."""

from __future__ import annotations

from rest_framework.permissions import BasePermission


class DenyAll(BasePermission):
    """Reject every request unless a view explicitly opts in."""

    def has_permission(self, request: object, view: object) -> bool:
        return False
