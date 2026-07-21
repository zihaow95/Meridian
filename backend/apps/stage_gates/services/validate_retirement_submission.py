"""Validate retirement plan completeness before gate submission."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from apps.operations.models import RetirementPlan
from apps.operations.services.retirement_plans import validate_retirement_plan_completeness
from apps.platform.api.errors import PermissionDeniedError
from apps.platform.application.command import CommandContext


@dataclass
class ValidateRetirementSubmission:
    context: CommandContext
    plan_public_id: UUID

    def execute(self) -> dict:
        actor = self.context.actor
        plan = (
            RetirementPlan.objects.select_related("operating_snapshot", "product")
            .filter(organization_id=actor.organization_id, public_id=self.plan_public_id)
            .first()
        )
        if plan is None:
            raise PermissionDeniedError()
        return validate_retirement_plan_completeness(plan)
