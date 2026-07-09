"""Helpers for MySQL-enforceable active opportunity membership keys."""

from __future__ import annotations


def active_membership_key(opportunity_id: int, user_id: int, member_role: str) -> str:
    return f"o{opportunity_id}:u{user_id}:{member_role}"
