"""Write iteration publish results back onto operating issues."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.operations.models import OperatingIssue, OperatingIssueStatus
from apps.products.models import ProductChangeSet, ProductVersion
from apps.projects.models import ProjectOpportunitySource


@dataclass
class HandleProductVersionPublished:
    event_id: UUID
    payload: dict[str, Any]

    def execute(self) -> OperatingIssue | None:
        change_set_id = self.payload.get("change_set_public_id")
        version_id = self.payload.get("product_version_public_id")
        if not change_set_id or not version_id:
            return None

        with transaction.atomic():
            change_set = (
                ProductChangeSet.objects.select_related("project", "product")
                .filter(public_id=change_set_id)
                .first()
            )
            version = ProductVersion.objects.filter(public_id=version_id).first()
            if change_set is None or version is None:
                return None
            project = change_set.project
            if project is None:
                return None

            sources = list(
                ProjectOpportunitySource.objects.filter(project_id=project.id).select_related(
                    "opportunity"
                )
            )
            if not sources:
                return None

            opportunity_ids = [source.opportunity.public_id for source in sources]
            issue = (
                OperatingIssue.objects.select_for_update()
                .filter(
                    linked_opportunity_id__in=opportunity_ids,
                    status=OperatingIssueStatus.CONVERTED_TO_PROPOSAL,
                    product_id=change_set.product_id,
                )
                .order_by("id")
                .first()
            )
            if issue is None:
                return None

            # Idempotent write-back: second replay keeps the first result.
            if issue.linked_product_version_id is not None:
                return issue

            effective_from = version.effective_from or timezone.now()
            raw_effective = (change_set.change_scope or {}).get("effective_from")
            if raw_effective:
                parsed = parse_datetime(str(raw_effective))
                if parsed is not None:
                    effective_from = (
                        parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
                    )

            issue.linked_project_id = project.public_id
            issue.linked_product_version_id = version.public_id
            issue.linked_effective_from = effective_from
            issue.version_no += 1
            issue.save(
                update_fields=[
                    "linked_project_id",
                    "linked_product_version_id",
                    "linked_effective_from",
                    "version_no",
                    "updated_at",
                ]
            )
            return issue
