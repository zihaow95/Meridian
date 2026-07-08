"""DRF permission classes backed by the authorization engine."""

from __future__ import annotations

from uuid import UUID

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.platform.api.errors import PermissionDeniedError


class RequiresPlatformAction(BasePermission):
    action_code: str = ""
    resource_type: str = ""
    resource_public_id: UUID | None = None

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not request.user or not request.user.is_authenticated:
            return False

        user = request.user
        resource_public_id = self.resource_public_id
        if resource_public_id is None and hasattr(view, "get_authorization_resource_public_id"):
            resource_public_id = view.get_authorization_resource_public_id()

        decision = authorize(
            subject_for(user),
            action=self.action_code,
            resource=ResourceDescriptor(
                resource_type=self.resource_type,
                public_id=resource_public_id,
                organization_id=user.organization_id,
            ),
            context=AuthorizationContext.current(),
        )
        if not decision.allowed:
            raise PermissionDeniedError()
        return True


def requires_action(*, action_code: str, resource_type: str) -> type[RequiresPlatformAction]:
    return type(
        f"Requires_{action_code.replace('.', '_')}",
        (RequiresPlatformAction,),
        {"action_code": action_code, "resource_type": resource_type},
    )
