"""Object identity provider granting minimal actions by product role."""

from __future__ import annotations

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ObjectIdentity,
    ResourceDescriptor,
)
from apps.authorization.policies.identity_provider import identity_registry

OWNER_ACTIONS: frozenset[str] = frozenset(
    {
        "product.read_basic",
        "product.read_sensitive",
        "product_version.history.read",
        "product_draft.create",
        "product_draft.edit_group",
        "product_draft.submit",
        "product_material.preview",
        "product_material.download_original",
        "product.export",
        "external_binding.manage",
    }
)

PROJECT_LEADER_ACTIONS: frozenset[str] = frozenset(
    {
        "product.read_basic",
        "product.read_sensitive",
        "product_version.history.read",
        "product_draft.edit_group",
        "product_material.preview",
        "product_material.download_original",
    }
)

PROJECT_MEMBER_ACTIONS: frozenset[str] = frozenset(
    {
        "product.read_basic",
        "product_version.history.read",
        "product_material.preview",
    }
)


class ProductIdentityProvider:
    resource_type = "product"

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        from apps.products.models import ProductAsset

        if resource.public_id is None:
            return ()

        product = ProductAsset.objects.filter(
            public_id=resource.public_id,
            organization_id=resource.organization_id,
        ).first()
        if product is None:
            return ()

        granted = self._granted_actions(product=product, subject=subject)
        return tuple(ObjectIdentity(action_code=action, resource=resource) for action in granted)

    def _granted_actions(
        self,
        *,
        product: object,
        subject: AuthorizationSubject,
    ) -> frozenset[str]:
        from apps.products.models import ProductAsset
        from apps.projects.models import ProjectMember, ProjectRole

        assert isinstance(product, ProductAsset)

        if product.product_owner_id == subject.user.id:
            return OWNER_ACTIONS

        if product.source_project_id is None:
            return frozenset()

        project = product.source_project
        if project is None:
            return frozenset()

        if project.leader_id == subject.user.id:
            return PROJECT_LEADER_ACTIONS

        is_member = ProjectMember.objects.filter(
            project=project,
            user=subject.user,
            project_role=ProjectRole.MEMBER,
            active_to__isnull=True,
        ).exists()
        if is_member:
            return PROJECT_MEMBER_ACTIONS

        return frozenset()


def register_providers() -> None:
    identity_registry.register(ProductIdentityProvider())
