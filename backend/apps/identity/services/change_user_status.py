"""User status transitions without deleting identity history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from apps.identity.models.user import User, UserStatus


class InvalidUserStatusTransition(Exception):
    pass


@dataclass(frozen=True)
class ChangeUserStatus:
    target: User
    status: str
    actor: User | None = None
    at: datetime | None = None

    def execute(self) -> User:
        if self.status not in UserStatus.values:
            raise InvalidUserStatusTransition(f"Unknown status: {self.status}")

        now = self.at or timezone.now()
        user = self.target
        user.status = self.status

        if self.status == UserStatus.ACTIVE:
            user.activated_at = now
        elif self.status == UserStatus.DISABLED:
            user.disabled_at = now
        elif self.status == UserStatus.DEPARTED:
            user.departed_at = now

        user.save(
            update_fields=[
                "status",
                "activated_at",
                "disabled_at",
                "departed_at",
                "updated_at",
            ]
        )
        return user
