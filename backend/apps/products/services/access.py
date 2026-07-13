"""Shared authorization helpers for product change-set reads."""

from __future__ import annotations

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.products.models import ProductChangeSet


def assert_can_read_change_set(*, user: User, change_set: ProductChangeSet) -> None:
    decision = authorize(
        subject_for(user),
        action="product.read_basic",
        resource=ResourceDescriptor(
            resource_type="product",
            public_id=change_set.product.public_id,
            organization_id=change_set.organization_id,
        ),
        context=AuthorizationContext.current(),
    )
    if not decision.allowed:
        raise PermissionDeniedError()
