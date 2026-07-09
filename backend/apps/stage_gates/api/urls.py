"""Stage gate API routes."""

from __future__ import annotations

from django.urls import path

from apps.stage_gates.api.decisions import (
    MajorGateDecisionView,
    ProposalReviewCycleView,
)

urlpatterns = [
    path(
        "opportunities/<uuid:public_id>/review-cycles",
        ProposalReviewCycleView.as_view(),
        name="opportunity-review-cycles",
    ),
    path(
        "stage-gates/<uuid:public_id>/major-decision",
        MajorGateDecisionView.as_view(),
        name="stage-gate-major-decision",
    ),
]
