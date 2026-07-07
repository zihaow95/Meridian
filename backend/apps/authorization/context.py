"""Authorization context and resource descriptors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from django.utils import timezone

from apps.authorization.models.role import DataSensitivityLevel
from apps.identity.models.user import User


@dataclass(frozen=True)
class ResourceDescriptor:
    resource_type: str
    public_id: UUID | None
    organization_id: int
    sensitivity_level: str = DataSensitivityLevel.INTERNAL
    scope_department_ids: frozenset[int] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectIdentity:
    action_code: str
    resource: ResourceDescriptor


@dataclass(frozen=True)
class AuthorizationSubject:
    user: User
    role_codes: frozenset[str]
    object_identities: tuple[ObjectIdentity, ...] = ()


@dataclass(frozen=True)
class AuthorizationContext:
    as_of: datetime
    department_ids: frozenset[int] = frozenset()

    @classmethod
    def current(cls, *, department_ids: frozenset[int] | None = None) -> AuthorizationContext:
        return cls(as_of=timezone.now(), department_ids=department_ids or frozenset())


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason_code: str
