"""Immutable proposal content versions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class ProposalVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    LOCKED = "LOCKED", "Locked"
    SUPERSEDED = "SUPERSEDED", "Superseded"


class ProposalVersionLocked(Exception):
    """Raised when a locked proposal version's content is mutated."""


_CONTENT_FIELDS = (
    "market_analysis",
    "core_selling_points",
    "target_users_needs",
    "suggested_retail_price",
    "content_snapshot",
)


class ProposalVersion(OrganizationOwnedModel):
    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    version_status = models.CharField(
        max_length=20,
        choices=ProposalVersionStatus.choices,
        default=ProposalVersionStatus.DRAFT,
    )
    market_analysis = models.TextField(blank=True, default="")
    core_selling_points = models.TextField(blank=True, default="")
    target_users_needs = models.TextField(blank=True, default="")
    suggested_retail_price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
    )
    content_snapshot = models.JSONField(default=dict)
    submitted_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opportunities_proposal_version"
        constraints = [
            models.UniqueConstraint(
                fields=["opportunity", "version_number"],
                name="opportunities_proposal_version_num_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["opportunity", "version_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.opportunity_id}:v{self.version_number}"

    def lock_for_review(self, *, now: datetime) -> None:
        self.version_status = ProposalVersionStatus.LOCKED
        self.locked_at = now
        self.save(update_fields=["version_status", "locked_at", "updated_at"])

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk:
            previous = (
                ProposalVersion.objects.filter(pk=self.pk)
                .values("version_status", *_CONTENT_FIELDS)
                .first()
            )
            if previous is not None and previous["version_status"] == ProposalVersionStatus.LOCKED:
                content_changed = any(
                    previous[field] != getattr(self, field) for field in _CONTENT_FIELDS
                )
                if content_changed:
                    raise ProposalVersionLocked(
                        "Locked proposal version content cannot be changed."
                    )
        super().save(*args, **kwargs)
