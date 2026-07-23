"""Provision the retirement system executor through a controlled admin entrypoint."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.authorization.models.assignment import AssignmentStatus, RoleAssignment, ScopeType
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleStatus,
    RoleType,
)
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.operations.services.system_actor import (
    SYSTEM_EMPLOYEE_NO,
    SYSTEM_ROLE_CODE,
)


class Command(BaseCommand):
    help = (
        "Provision (or report) the ACTIVE retirement system executor principal "
        "for one or all organizations. Does not reactivate a DISABLED executor."
    )

    def add_arguments(self, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument(
            "--organization-id",
            type=int,
            default=None,
            help="Limit provisioning to a single organization primary key.",
        )
        parser.add_argument(
            "--actor-login-key",
            type=str,
            default=None,
            help="login_key of the admin performing this audited provision.",
        )

    def handle(self, *args, **options) -> None:  # type: ignore[no-untyped-def]
        org_id = options.get("organization_id")
        orgs = Organization.objects.all().order_by("id")
        if org_id is not None:
            orgs = orgs.filter(pk=org_id)
        actor = None
        login_key = options.get("actor_login_key")
        if login_key:
            actor = User.objects.filter(login_key=login_key, status=UserStatus.ACTIVE).first()
            if actor is None:
                raise SystemExit(f"Active admin with login_key={login_key!r} not found.")

        for organization in orgs:
            user = self._provision(organization=organization, actor=actor)
            self.stdout.write(
                self.style.SUCCESS(
                    f"organization={organization.id} executor={user.public_id} "
                    f"employee_no={user.employee_no} status={user.status}"
                )
            )

    def _provision(self, *, organization: Organization, actor: User | None) -> User:
        with transaction.atomic():
            existing = User.objects.filter(
                organization=organization, employee_no=SYSTEM_EMPLOYEE_NO
            ).first()
            if existing is not None and existing.status != UserStatus.ACTIVE:
                raise SystemExit(
                    f"organization={organization.id}: executor exists but status="
                    f"{existing.status}; refusing to reactivate. Restore via "
                    "controlled identity admin workflow."
                )
            if existing is None:
                user = User.objects.create_user(
                    organization=organization,
                    display_name="System Retirement Executor",
                    employee_no=SYSTEM_EMPLOYEE_NO,
                    status=UserStatus.ACTIVE,
                )
                user.set_unusable_password()
                user.save(update_fields=["password", "updated_at"])
            else:
                user = existing
                if user.has_usable_password():
                    user.set_unusable_password()
                    user.save(update_fields=["password", "updated_at"])

            role, _ = Role.objects.get_or_create(
                role_code=SYSTEM_ROLE_CODE,
                defaults={
                    "name": "System Retirement Executor",
                    "role_type": RoleType.BUSINESS,
                    "status": RoleStatus.ACTIVE,
                },
            )
            action, _ = PermissionAction.objects.get_or_create(
                action_code="retirement_plan.execute",
                defaults={
                    "resource_type": "retirement_plan",
                    "action_category": ActionCategory.WRITE,
                    "description": "Execute approved retirement plan actions",
                },
            )
            RolePermission.objects.get_or_create(
                role=role,
                action=action,
                defaults={
                    "max_data_level": DataSensitivityLevel.HIGHLY_SENSITIVE,
                    "requires_object_scope": False,
                },
            )
            assignment = (
                RoleAssignment.objects.filter(
                    user=user,
                    role=role,
                    scope_type=ScopeType.ORGANIZATION,
                )
                .order_by("id")
                .first()
            )
            now = timezone.now()
            if assignment is None:
                RoleAssignment.objects.create(
                    user=user,
                    role=role,
                    scope_type=ScopeType.ORGANIZATION,
                    scope_id=organization.id,
                    effective_from=user.created_at or now,
                    effective_to=None,
                    configured_by=actor or user,
                    status=AssignmentStatus.ACTIVE,
                )
            elif assignment.status != AssignmentStatus.ACTIVE:
                raise SystemExit(
                    f"organization={organization.id}: executor assignment is "
                    f"{assignment.status}; refusing to self-heal."
                )

            if actor is not None:
                append_event(
                    AuditRecord(
                        actor=actor,
                        action_code="system_actor.retirement.provision",
                        resource_type="user",
                        resource_public_id=user.public_id,
                        result=AuditResult.SUCCESS,
                        trace_id=f"provision-retirement-system-actor:{organization.id}",
                        occurred_at=now,
                        after_summary={
                            "organization_id": organization.id,
                            "employee_no": SYSTEM_EMPLOYEE_NO,
                            "role_code": SYSTEM_ROLE_CODE,
                        },
                    )
                )
            return user
