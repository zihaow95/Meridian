"""Helpers for MySQL-enforceable active project membership keys."""

from __future__ import annotations


def active_member_key(project_id: int, user_id: int, project_role: str) -> str:
    return f"p{project_id}:u{user_id}:{project_role}"
