"""Provision the retirement system executor via controlled authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.assignment import (
    AssignmentStatus,
    RoleAssignment,
    ScopeType,
    build_scope_key,
)
from apps.authorization.models.role import (
    ActionCategory,
    DataSensitivityLevel,
    PermissionAction,
    Role,
    RolePermission,
    RoleStatus,
    RoleType,
)
from apps.authorization.policies.engine import authorize
from apps.authorization.services.role_assignment_locks import lock_organization_and_users
from apps.authorization.services.subject import subject_for
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
from apps.identity.services.ensure_system_executor import EnsureRetirementSystemExecutor
from apps.operations.services.system_actor import SYSTEM_EMPLOYEE_NO, SYSTEM_ROLE_CODE
from apps.platform.api.errors import PermissionDeniedError, ValidationFailedError
from apps.platform.application.command import CommandContext

_ACTION = "system_actor.retirement.provision"
_EXECUTE_ACTION = "retirement_plan.execute"


class ProvisionRetirementSystemActorDenied(PermissionDeniedError):
    """Raised when the actor lacks provision / role-assign authority."""


@dataclass(frozen=True)
class ProvisionRetirementSystemActor:
    """Create or confirm the ACTIVE retirement executor for one organization.

    Requires an authenticated CommandContext actor in the target organization
    who holds both ``system_actor.retirement.provision`` and
    ``authorization.role.assign``. Never self-configures as ``configured_by``.
    """

    context: CommandContext
    organization: Organization

    def execute(self) -> User:
        actor = self.context.actor
        now = self.context.occurred_at

        if actor.status != UserStatus.ACTIVE:
            self._audit_failure(actor=actor, reason="actor_not_active", now=now)
            raise ProvisionRetirementSystemActorDenied()

        if actor.organization_id != self.organization.id:
            self._audit_failure(actor=actor, reason="organization_mismatch", now=now)
            raise ProvisionRetirementSystemActorDenied()

        try:
            with transaction.atomic():
                lock_organization_and_users(
                    organization_id=self.organization.id,
                    user_ids=(actor.id,),
                )
                if not self._allowed(actor):
                    raise ProvisionRetirementSystemActorDenied()
                user = EnsureRetirementSystemExecutor(
                    context=self.context,
                    organization=self.organization,
                    employee_no=SYSTEM_EMPLOYEE_NO,
                ).execute()
                role = self._ensure_role_and_permission()
                self._ensure_assignment(user=user, role=role, actor=actor, now=now)
                append_event(
                    AuditRecord(
                        actor=actor,
                        action_code=_ACTION,
                        resource_type="user",
                        resource_public_id=user.public_id,
                        result=AuditResult.SUCCESS,
                        trace_id=self.context.trace_id,
                        occurred_at=now,
                        acting_roles_snapshot=acting_roles_snapshot(actor),
                        after_summary={
                            "organization_id": self.organization.id,
                            "employee_no": SYSTEM_EMPLOYEE_NO,
                            "role_code": SYSTEM_ROLE_CODE,
                        },
                    )
                )
                return user
        except ProvisionRetirementSystemActorDenied:
            self._audit_failure(actor=actor, reason="authorization_denied", now=now)
            raise
        except ValidationFailedError as exc:
            reason = self._reason_from_validation(exc)
            self._audit_failure(actor=actor, reason=reason, now=now)
            raise

    def _reason_from_validation(self, exc: ValidationFailedError) -> str:
        message = (exc.message or "").lower()
        if "not active" in message and "executor exists" in message:
            return "executor_inactive"
        if "role is not active" in message:
            return "role_inactive"
        if "assignment is inactive" in message:
            return "assignment_inactive"
        return "validation_failed"

    def _allowed(self, actor: User) -> bool:
        subject = subject_for(actor)
        context = AuthorizationContext.current()
        provision = authorize(
            subject,
            action=_ACTION,
            resource=ResourceDescriptor(
                resource_type="system_actor",
                public_id=None,
                organization_id=self.organization.id,
            ),
            context=context,
        )
        assign = authorize(
            subject,
            action="authorization.role.assign",
            resource=ResourceDescriptor(
                resource_type="authorization.role",
                public_id=None,
                organization_id=self.organization.id,
            ),
            context=context,
        )
        return provision.allowed and assign.allowed

    def _audit_failure(self, *, actor: User, reason: str, now: datetime) -> None:
        append_event(
            AuditRecord(
                actor=actor,
                action_code=_ACTION,
                resource_type="system_actor",
                resource_public_id=None,
                result=AuditResult.FAILURE,
                trace_id=self.context.trace_id,
                occurred_at=now,
                acting_roles_snapshot=acting_roles_snapshot(actor),
                after_summary={
                    "organization_id": self.organization.id,
                    "reason": reason,
                },
                reason=reason,
            )
        )

    def _ensure_role_and_permission(self) -> Role:
        role, _ = Role.objects.get_or_create(
            role_code=SYSTEM_ROLE_CODE,
            defaults={
                "name": "System Retirement Executor",
                "role_type": RoleType.BUSINESS,
                "status": RoleStatus.ACTIVE,
            },
        )
        if role.status != RoleStatus.ACTIVE:
            raise ValidationFailedError(message="Retirement system executor role is not ACTIVE.")
        action, _ = PermissionAction.objects.get_or_create(
            action_code=_EXECUTE_ACTION,
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
        return role

    def _ensure_assignment(
        self, *, user: User, role: Role, actor: User, now: datetime
    ) -> RoleAssignment:
        scope_key = build_scope_key(
            scope_type=ScopeType.ORGANIZATION, scope_id=self.organization.id
        )
        base = RoleAssignment.objects.select_for_update().filter(
            user=user,
            role=role,
            scope_type=ScopeType.ORGANIZATION,
            scope_key=scope_key,
        )
        active = (
            base.filter(
                status=AssignmentStatus.ACTIVE,
                effective_to__isnull=True,
                active_slot=1,
            )
            .order_by("id")
            .first()
        )
        if active is not None:
            return active
        if base.exists():
            raise ValidationFailedError(
                message=(
                    "Retirement system executor assignment is inactive; "
                    "refusing to self-heal via provision."
                )
            )
        return RoleAssignment.objects.create(
            user=user,
            role=role,
            scope_type=ScopeType.ORGANIZATION,
            scope_id=self.organization.id,
            scope_key=scope_key,
            effective_from=user.created_at or now,
            effective_to=None,
            configured_by=actor,
            status=AssignmentStatus.ACTIVE,
            active_slot=1,
        )
