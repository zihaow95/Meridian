"""Authorization domain models."""

from __future__ import annotations

from apps.authorization.models.assignment import RoleAssignment
from apps.authorization.models.role import PermissionAction, Role, RolePermission

__all__ = ["PermissionAction", "Role", "RoleAssignment", "RolePermission"]
