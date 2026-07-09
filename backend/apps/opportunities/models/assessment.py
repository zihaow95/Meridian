"""Case assessment rows: the eight fixed core categories per candidate."""

from __future__ import annotations

from django.db import models

from apps.platform.models.base import OrganizationOwnedModel


class AssessmentCategory(models.TextChoices):
    PRODUCTION_PARTY = "PRODUCTION_PARTY", "Production party"
    COOPERATION = "COOPERATION", "Cooperation"
    FACTORY = "FACTORY", "Factory"
    PROCESS = "PROCESS", "Process"
    RAW_PACKAGING = "RAW_PACKAGING", "Raw and packaging"
    COST = "COST", "Cost"
    SCHEDULE = "SCHEDULE", "Schedule"
    RISK = "RISK", "Risk"


# The core assessment set is fixed by the TRD; submitting for project review
# requires every one of these to be resolved.
CORE_ASSESSMENT_CATEGORIES: tuple[str, ...] = tuple(AssessmentCategory.values)


class AssessmentStatus(models.TextChoices):
    NOT_STARTED = "NOT_STARTED", "Not started"
    IN_PROGRESS = "IN_PROGRESS", "In progress"
    READY = "READY", "Ready"
    CONFIRMED = "CONFIRMED", "Confirmed"
    EXEMPTED = "EXEMPTED", "Exempted"


# States that count as "resolved" when gating a project-review submission.
RESOLVED_ASSESSMENT_STATUSES: frozenset[str] = frozenset(
    {AssessmentStatus.CONFIRMED, AssessmentStatus.EXEMPTED}
)


class CaseAssessment(OrganizationOwnedModel):
    candidate = models.ForeignKey(
        "opportunities.ProjectCandidate",
        on_delete=models.PROTECT,
        related_name="assessments",
    )
    category_code = models.CharField(max_length=32, choices=AssessmentCategory.choices)
    conclusion = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=AssessmentStatus.choices,
        default=AssessmentStatus.NOT_STARTED,
    )
    # Controlled deliverable reference; must point at a CONTROLLED document version.
    deliverable_version_public_id = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "opportunities_case_assessment"
        constraints = [
            models.UniqueConstraint(
                fields=["candidate", "category_code"],
                name="opportunities_assessment_cat_uniq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.candidate_id}:{self.category_code}"
