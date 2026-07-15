"""Object identity providers for tasks, deliverables, and confirmations."""

from __future__ import annotations

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ObjectIdentity,
    ResourceDescriptor,
)
from apps.authorization.policies.identity_provider import identity_registry

RESPONSIBLE_ACTIONS: frozenset[str] = frozenset({"task.update_own"})
LEADER_DELIVERABLE_ACTIONS: frozenset[str] = frozenset({"deliverable.create", "revision.submit"})


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
            for action in (
                "project.read",
                "plan.edit",
                "member.manage",
                "plan_change.apply_minor",
            )
        )


class ProjectStageIdentityProvider:
    resource_type = "project_stage"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.projects.models import ProjectStage

        del context
        if resource.public_id is None:
            return ()
        stage = (
            ProjectStage.objects.select_related("project")
            .filter(
                public_id=resource.public_id,
                organization_id=resource.organization_id,
            )
            .first()
        )
        if stage is None:
            return ()
        if stage.project.leader_id != subject.user.id:
            return ()
        return (ObjectIdentity(action_code="stage_handling.request", resource=resource),)


class DeliverableIdentityProvider:
    resource_type = "deliverable"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.work_items.models import Deliverable

        del context
        if resource.public_id is None:
            return ()
        deliverable = (
            Deliverable.objects.select_related("project")
            .filter(
                public_id=resource.public_id,
                organization_id=resource.organization_id,
            )
            .first()
        )
        if deliverable is None:
            return ()
        if deliverable.project.leader_id != subject.user.id:
            return ()
        return tuple(
            ObjectIdentity(action_code=action, resource=resource)
            for action in ("deliverable.create",)
        )


class DeliverableRevisionIdentityProvider:
    resource_type = "deliverable_revision"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.work_items.models import DeliverableRevision

        del context
        if resource.public_id is None:
            return ()
        revision = (
            DeliverableRevision.objects.select_related("deliverable__project")
            .filter(
                public_id=resource.public_id,
                organization_id=resource.organization_id,
            )
            .first()
        )
        if revision is None:
            return ()
        if revision.deliverable.project.leader_id != subject.user.id:
            return ()
        return tuple(ObjectIdentity(action_code="revision.submit", resource=resource) for _ in (1,))


class ProfessionalConfirmationIdentityProvider:
    resource_type = "professional_confirmation"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.work_items.models import ProfessionalConfirmation

        del context
        if resource.public_id is None:
            return ()
        confirmation = ProfessionalConfirmation.objects.filter(
            public_id=resource.public_id,
            organization_id=resource.organization_id,
        ).first()
        if confirmation is None:
            return ()
        if confirmation.confirmer_id != subject.user.id:
            return ()
        return (
            ObjectIdentity(
                action_code="professional_confirmation.decide",
                resource=resource,
            ),
        )


def register_providers() -> None:
    identity_registry.register(TaskIdentityProvider())
    identity_registry.register(ProjectIdentityProvider())
    identity_registry.register(ProjectStageIdentityProvider())
    identity_registry.register(DeliverableIdentityProvider())
    identity_registry.register(DeliverableRevisionIdentityProvider())
    identity_registry.register(ProfessionalConfirmationIdentityProvider())
