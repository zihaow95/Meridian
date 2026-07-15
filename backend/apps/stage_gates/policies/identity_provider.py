"""Object identity for execution stage gates."""

from __future__ import annotations

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ObjectIdentity,
    ResourceDescriptor,
)
from apps.authorization.policies.identity_provider import identity_registry

LEADER_ACTIONS: frozenset[str] = frozenset(
    {
        "stage_gate.submit",
        "normal_gate.decide",
    }
)


class StageGateIdentityProvider:
    resource_type = "stage_gate"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.stage_gates.models import StageGateInstance, SubjectType

        del context
        if resource.public_id is None:
            return ()
        gate = (
            StageGateInstance.objects.select_related("project")
            .filter(
                public_id=resource.public_id,
                organization_id=resource.organization_id,
            )
            .first()
        )
        if gate is None:
            return ()
        if gate.subject_type != SubjectType.PROJECT or gate.project_id is None:
            return ()
        if gate.project.leader_id != subject.user.id:
            return ()
        return tuple(
            ObjectIdentity(action_code=action, resource=resource) for action in LEADER_ACTIONS
        )


def register_providers() -> None:
    identity_registry.register(StageGateIdentityProvider())
