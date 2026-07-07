"""Object identity provider extension point for business domains."""

from __future__ import annotations

from typing import Protocol

from apps.authorization.context import (
    AuthorizationContext,
    AuthorizationSubject,
    ObjectIdentity,
    ResourceDescriptor,
)


class ObjectIdentityProvider(Protocol):
    resource_type: str

    def resolve_identities(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        """Return project/business identities for the subject on the given resource."""


class ObjectIdentityRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ObjectIdentityProvider] = {}

    def register(self, provider: ObjectIdentityProvider) -> None:
        self._providers[provider.resource_type] = provider

    def resolve(
        self,
        *,
        subject: AuthorizationSubject,
        resource: ResourceDescriptor,
        context: AuthorizationContext,
    ) -> tuple[ObjectIdentity, ...]:
        provider = self._providers.get(resource.resource_type)
        if provider is None:
            return ()
        return provider.resolve_identities(subject=subject, resource=resource, context=context)


identity_registry = ObjectIdentityRegistry()
