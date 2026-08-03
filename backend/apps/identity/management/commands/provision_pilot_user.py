"""Create or update one explicit pilot account with non-critical roles.

Critical roles stay on the approved assignment path. This command never grants
them, never invents a shared demo account, and never writes the password into
logs or audit summaries.
"""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.authorization.models.assignment import (
    AssignmentStatus,
    RoleAssignment,
    ScopeType,
    build_scope_key,
    resolve_scope_id,
)
from apps.authorization.models.role import Role, RoleStatus
from apps.identity.models.organization import Organization, OrganizationStatus
from apps.identity.models.user import User, UserStatus


class Command(BaseCommand):
    help = "Provision one pilot user with employee_no, password and non-critical roles."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--organization-public-id", required=True)
        parser.add_argument("--employee-no", required=True)
        parser.add_argument("--display-name", required=True)
        parser.add_argument("--password", required=True)
        parser.add_argument(
            "--roles",
            required=True,
            help="Comma-separated non-critical role codes.",
        )
        parser.add_argument(
            "--configured-by-login-key",
            required=True,
            help="Existing operator who is recorded as configured_by.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        organization = Organization.objects.filter(
            public_id=options["organization_public_id"]
        ).first()
        if organization is None or organization.status != OrganizationStatus.ACTIVE:
            raise CommandError("Organization is missing or inactive.")

        configured_by = User.objects.filter(
            login_key=options["configured_by_login_key"],
            organization=organization,
            status=UserStatus.ACTIVE,
        ).first()
        if configured_by is None:
            raise CommandError("configured_by operator was not found or is inactive.")

        role_codes = [code.strip() for code in str(options["roles"]).split(",") if code.strip()]
        if not role_codes:
            raise CommandError("At least one role code is required.")

        roles = list(Role.objects.filter(role_code__in=role_codes, status=RoleStatus.ACTIVE))
        found = {role.role_code for role in roles}
        missing = sorted(set(role_codes) - found)
        if missing:
            raise CommandError(f"Unknown or inactive roles: {', '.join(missing)}")
        critical = sorted(role.role_code for role in roles if role.is_critical)
        if critical:
            raise CommandError(
                "Critical roles cannot be granted by this command: " + ", ".join(critical)
            )

        employee_no = str(options["employee_no"]).strip()
        if not employee_no:
            raise CommandError("employee_no is required.")

        with transaction.atomic():
            user = User.objects.filter(organization=organization, employee_no=employee_no).first()
            created = user is None
            if user is None:
                user = User.objects.create_user(
                    organization=organization,
                    display_name=str(options["display_name"]).strip(),
                    employee_no=employee_no,
                    password=str(options["password"]),
                    status=UserStatus.ACTIVE,
                    activated_at=timezone.now(),
                )
            else:
                user.display_name = str(options["display_name"]).strip()
                user.status = UserStatus.ACTIVE
                if user.activated_at is None:
                    user.activated_at = timezone.now()
                user.set_password(str(options["password"]))
                user.save()

            now = timezone.now()
            scope_id = resolve_scope_id(
                scope_type=ScopeType.ORGANIZATION,
                scope_id=organization.id,
                organization_id=organization.id,
            )
            scope_key = build_scope_key(scope_type=ScopeType.ORGANIZATION, scope_id=scope_id)
            for role in roles:
                assignment = RoleAssignment.objects.filter(
                    user=user,
                    role=role,
                    scope_type=ScopeType.ORGANIZATION,
                    scope_key=scope_key,
                    active_slot=1,
                ).first()
                if assignment is None:
                    RoleAssignment.objects.create(
                        user=user,
                        role=role,
                        scope_type=ScopeType.ORGANIZATION,
                        scope_id=scope_id,
                        scope_key=scope_key,
                        effective_from=now,
                        configured_by=configured_by,
                        status=AssignmentStatus.ACTIVE,
                        active_slot=1,
                    )

            # Password must never appear in the audit summary.
            append_event(
                AuditRecord(
                    actor=configured_by,
                    action_code="identity.pilot_account.provision",
                    resource_type="identity.user",
                    resource_public_id=user.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id="provision-pilot-user",
                    occurred_at=now,
                    after_summary={
                        "employee_no": employee_no,
                        "organization_public_id": str(organization.public_id),
                        "created": created,
                        "roles": sorted(role.role_code for role in roles),
                    },
                    reason="CREATED" if created else "UPDATED",
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{'Created' if created else 'Updated'} pilot user "
                f"employee_no={employee_no} public_id={user.public_id}"
            )
        )
