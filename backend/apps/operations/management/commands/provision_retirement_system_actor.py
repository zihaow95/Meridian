"""CLI wrapper around the controlled retirement system actor provision service."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.authorization.services.provision_retirement_system_actor import (
    ProvisionRetirementSystemActor,
    ProvisionRetirementSystemActorDenied,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext


class Command(BaseCommand):
    help = (
        "Provision the ACTIVE retirement system executor for exactly one organization "
        "using a required authorized actor. Does not reactivate DISABLED principals."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--organization-id",
            type=int,
            required=True,
            help="Organization primary key to provision (required).",
        )
        parser.add_argument(
            "--actor-login-key",
            type=str,
            required=True,
            help="login_key of the authorized admin performing this provision (required).",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        org_id = options["organization_id"]
        login_key = options["actor_login_key"]
        organization = Organization.objects.filter(pk=org_id).first()
        if organization is None:
            raise CommandError(f"Organization id={org_id} not found.")
        actor = User.objects.filter(login_key=login_key, status=UserStatus.ACTIVE).first()
        if actor is None:
            raise CommandError(f"Active admin with login_key={login_key!r} not found.")

        try:
            user = ProvisionRetirementSystemActor(
                context=CommandContext.for_actor(actor),
                organization=organization,
            ).execute()
        except (ProvisionRetirementSystemActorDenied, PermissionDeniedError) as exc:
            raise CommandError("Provision denied: actor lacks required admin grants.") from exc
        except ValidationFailedError as exc:
            raise CommandError(str(exc.message)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"organization={organization.id} executor={user.public_id} "
                f"employee_no={user.employee_no} status={user.status}"
            )
        )
