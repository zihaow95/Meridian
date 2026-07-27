"""Provision the retirement system executor via controlled authorization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import IntegrityError, transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
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
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.organization import Organization
from apps.identity.models.user import User, UserStatus
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

        if not self._allowed(actor):
            self._audit_failure(actor=actor, reason="authorization_denied", now=now)
            raise ProvisionRetirementSystemActorDenied()

        try:
            with transaction.atomic():
                # Serialize provision per organization (MySQL lacks conditional
                # unique indexes used elsewhere for employee_no).
                Organization.objects.select_for_update().get(pk=self.organization.pk)
                user = self._ensure_executor(actor=actor, now=now)
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
        except IntegrityError:
            # Concurrent provision: return the winner's row if still active.
            existing = User.objects.filter(
                organization=self.organization,
                employee_no=SYSTEM_EMPLOYEE_NO,
                status=UserStatus.ACTIVE,
            ).first()
            if existing is None:
                raise
            return existing

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

    def _ensure_executor(self, *, actor: User, now: datetime) -> User:
        existing = (
            User.objects.select_for_update()
            .filter(organization=self.organization, employee_no=SYSTEM_EMPLOYEE_NO)
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
                display_name="System Retirement Executor",
                employee_no=SYSTEM_EMPLOYEE_NO,
                status=UserStatus.ACTIVE,
            )
            user.set_unusable_password()
            user.save(update_fields=["password", "updated_at"])
            return user
        if existing.has_usable_password():
            existing.set_unusable_password()
            existing.save(update_fields=["password", "updated_at"])
        return existing

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
        assignment = (
            RoleAssignment.objects.select_for_update()
            .filter(
                user=user,
                role=role,
                scope_type=ScopeType.ORGANIZATION,
                scope_id=self.organization.id,
            )
            .order_by("id")
            .first()
        )
        if assignment is None:
            return RoleAssignment.objects.create(
                user=user,
                role=role,
                scope_type=ScopeType.ORGANIZATION,
                scope_id=self.organization.id,
                effective_from=user.created_at or now,
                effective_to=None,
                configured_by=actor,
                status=AssignmentStatus.ACTIVE,
                active_slot=1,
            )
        if (
            assignment.status != AssignmentStatus.ACTIVE
            or assignment.effective_to is not None
            or assignment.active_slot != 1
        ):
            raise ValidationFailedError(
                message=(
                    "Retirement system executor assignment is inactive; "
                    "refusing to self-heal via provision."
                )
            )
        return assignment
