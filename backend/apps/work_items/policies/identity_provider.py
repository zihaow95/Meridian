"""Object identity provider for task resources."""

from __future__ import annotations

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ObjectIdentity,
    ResourceDescriptor,
)
from apps.authorization.policies.identity_provider import identity_registry


RESPONSIBLE_ACTIONS: frozenset[str] = frozenset({"task.update_own"})


class TaskIdentityProvider:
    resource_type = "task"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.work_items.models import Task

        del context
        if resource.public_id is None:
            return ()

        task = Task.objects.filter(
            public_id=resource.public_id,
            organization_id=resource.organization_id,
        ).first()
        if task is None:
            return ()

        granted: set[str] = set()
        if task.responsible_user_id == subject.user.id:
            granted.update(RESPONSIBLE_ACTIONS)
        return tuple(ObjectIdentity(action_code=action, resource=resource) for action in granted)


class ProjectIdentityProvider:
    resource_type = "project"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.projects.models import Project

        del context
        if resource.public_id is None:
            return ()
        project = Project.objects.filter(
            public_id=resource.public_id,
            organization_id=resource.organization_id,
        ).first()
        if project is None:
            return ()
        if project.leader_id != subject.user.id:
            return ()
        return tuple(
            ObjectIdentity(action_code=action, resource=resource)
            for action in ("project.read", "plan.edit", "member.manage")
        )


def register_providers() -> None:
    identity_registry.register(TaskIdentityProvider())
    identity_registry.register(ProjectIdentityProvider())
