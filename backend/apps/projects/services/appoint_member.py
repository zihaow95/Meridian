"""Appoint or replace active project membership."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.db import transaction

from apps.audit.models import AuditResult
from apps.audit.services.append_event import AuditRecord, append_event
from apps.audit.services.snapshots import acting_roles_snapshot
from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User, UserStatus
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext
from apps.projects.member_keys import active_member_key
from apps.projects.models import Project, ProjectMember, ProjectRole


@dataclass
class AppointProjectMember:
    context: CommandContext
    project_public_id: UUID
    user_public_id: UUID
    project_role: str = ProjectRole.MEMBER

    def execute(self) -> ProjectMember:
        actor = self.context.actor
        if self.project_role not in ProjectRole.values:
            raise PermissionDeniedError()
        with transaction.atomic():
            project = Project.objects.select_for_update().filter(
                public_id=self.project_public_id,
                organization_id=actor.organization_id,
            ).first()
            if project is None:
                raise PermissionDeniedError()
            decision = authorize(
                subject_for(actor),
                action="member.manage",
                resource=ResourceDescriptor(
                    resource_type="project",
                    public_id=project.public_id,
                    organization_id=project.organization_id,
                ),
                context=AuthorizationContext.current(),
            )
            if not decision.allowed and project.leader_id != actor.id:
                raise PermissionDeniedError()

            member_user = User.objects.filter(
                public_id=self.user_public_id,
                organization_id=actor.organization_id,
                status=UserStatus.ACTIVE,
            ).first()
            if member_user is None:
                raise PermissionDeniedError()

            existing = ProjectMember.objects.filter(
                project=project,
                user=member_user,
                active_to__isnull=True,
            ).first()
            if existing is not None:
                if existing.project_role == self.project_role:
                    return existing
                existing.active_to = self.context.occurred_at
                existing.active_role_key = None
                existing.save(update_fields=["active_to", "active_role_key"])

            member = ProjectMember.objects.create(
                organization=project.organization,
                project=project,
                user=member_user,
                project_role=self.project_role,
                active_role_key=active_member_key(
                    project.id, member_user.id, self.project_role
                ),
                active_from=self.context.occurred_at,
                appointed_by=actor,
            )
            append_event(
                AuditRecord(
                    actor=actor,
                    action_code="member.manage",
                    resource_type="project",
                    resource_public_id=project.public_id,
                    result=AuditResult.SUCCESS,
                    trace_id=self.context.trace_id,
                    occurred_at=self.context.occurred_at,
                    acting_roles_snapshot=acting_roles_snapshot(actor),
                    after_summary={
                        "member_public_id": str(member.public_id),
                        "user_public_id": str(member_user.public_id),
                        "project_role": member.project_role,
                    },
                )
            )
            return member
