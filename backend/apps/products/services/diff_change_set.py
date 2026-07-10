"""Build structured diffs between a change set and its baseline snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.models.role import LEVEL_RANK, DataSensitivityLevel
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.platform.api.errors import PermissionDeniedError
from apps.products.models import (
    AttributeGroupValue,
    AttributeOwnerType,
    AttributeValueStatus,
    ProductChangeSet,
)


@dataclass(frozen=True)
class FieldDiff:
    group_code: str
    field_code: str
    field_name: str
    old_value: Any
    new_value: Any
    sensitivity_level: str
    edited_by_public_id: str | None
    edited_at: datetime | None
    confirmation_status: str | None = None


@dataclass(frozen=True)
class ChangeSetDiffResult:
    change_set_public_id: UUID
    changed_fields: tuple[FieldDiff, ...]


@dataclass
class BuildProductChangeSetDiff:
    actor: User
    change_set_public_id: UUID

    def execute(self) -> ChangeSetDiffResult:
        change_set = (
            ProductChangeSet.objects.select_related("product", "base_version")
            .filter(
                public_id=self.change_set_public_id,
                organization_id=self.actor.organization_id,
            )
            .first()
        )
        if change_set is None:
            raise PermissionDeniedError()

        can_read_sensitive = authorize(
            subject_for(self.actor),
            action="product.read_sensitive",
            resource=ResourceDescriptor(
                resource_type="product",
                public_id=change_set.product.public_id,
                organization_id=change_set.organization_id,
                sensitivity_level=DataSensitivityLevel.SENSITIVE_CONTROLLED,
            ),
            context=AuthorizationContext.current(),
        ).allowed

        baseline_values = _baseline_group_values(change_set)
        draft_values = {
            value.group_definition.group_code: value
            for value in AttributeGroupValue.objects.filter(
                change_set=change_set,
                value_status=AttributeValueStatus.DRAFT,
            ).select_related("group_definition", "edited_by")
        }

        changed_fields: list[FieldDiff] = []
        for group_code, draft_value in sorted(draft_values.items()):
            baseline_group = baseline_values.get(group_code, {})
            field_definitions = {
                definition.field_code: definition
                for definition in draft_value.group_definition.field_definitions.all()
            }
            for field_code, definition in sorted(field_definitions.items()):
                old_value = baseline_group.get(field_code)
                new_value = draft_value.values_json.get(field_code)
                if old_value == new_value:
                    continue
                changed_fields.append(
                    FieldDiff(
                        group_code=group_code,
                        field_code=field_code,
                        field_name=definition.field_name,
                        old_value=_project_value(
                            definition.sensitivity_level,
                            old_value,
                            can_read_sensitive=can_read_sensitive,
                        ),
                        new_value=_project_value(
                            definition.sensitivity_level,
                            new_value,
                            can_read_sensitive=can_read_sensitive,
                        ),
                        sensitivity_level=definition.sensitivity_level,
                        edited_by_public_id=(
                            str(draft_value.edited_by.public_id) if draft_value.edited_by else None
                        ),
                        edited_at=draft_value.updated_at,
                    )
                )

        return ChangeSetDiffResult(
            change_set_public_id=change_set.public_id,
            changed_fields=tuple(changed_fields),
        )


def _baseline_group_values(change_set: ProductChangeSet) -> dict[str, dict[str, Any]]:
    if change_set.base_version_id is None:
        return {}

    baseline_rows = AttributeGroupValue.objects.filter(
        organization_id=change_set.organization_id,
        owner_type=AttributeOwnerType.VERSION,
        owner_id=change_set.base_version_id,
        value_status=AttributeValueStatus.EFFECTIVE,
        change_set__isnull=True,
    ).select_related("group_definition")
    return {row.group_definition.group_code: dict(row.values_json) for row in baseline_rows}


def _project_value(
    sensitivity_level: str,
    value: Any,
    *,
    can_read_sensitive: bool,
) -> Any:
    if value is None:
        return None
    required_rank = LEVEL_RANK.get(sensitivity_level, 0)
    allowed_rank = LEVEL_RANK.get(DataSensitivityLevel.SENSITIVE_CONTROLLED, 0)
    if required_rank > allowed_rank and not can_read_sensitive:
        return "[restricted]"
    return value
