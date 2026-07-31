"""Controlled creation of non-interactive system executor principals."""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext


@dataclass(frozen=True)
class EnsureRetirementSystemExecutor:
    """Create or confirm an ACTIVE retirement system executor user.

    Does not reactivate DISABLED/DEPARTED principals. Always leaves the
    password unusable. Authorization/auditing of the broader provision flow
    remains in the calling authorization application service.
    """

    context: CommandContext
    organization: Organization
    employee_no: str
    display_name: str = "System Retirement Executor"

    def execute(self) -> User:
        actor = self.context.actor
        if actor.organization_id != self.organization.id:
            raise ValidationFailedError(message="System executor org mismatch.")
        if not self.employee_no:
            raise ValidationFailedError(message="employee_no is required.")

        with transaction.atomic():
            existing = (
                User.objects.select_for_update()
                .filter(organization=self.organization, employee_no=self.employee_no)
                .first()
            )
            if existing is not None and existing.status != UserStatus.ACTIVE:
                raise ValidationFailedError(
                    message=(
                        "Retirement system executor exists but is not ACTIVE; "
                        "refusing to reactivate via provision."
                    )
                )
            if existing is None:
                user = User.objects.create_user(
                    organization=self.organization,
                    display_name=self.display_name,
                    employee_no=self.employee_no,
                    status=UserStatus.ACTIVE,
                )
                user.set_unusable_password()
                user.save(update_fields=["password", "updated_at"])
                return user
            if existing.has_usable_password():
                existing.set_unusable_password()
                existing.save(update_fields=["password", "updated_at"])
            return existing
