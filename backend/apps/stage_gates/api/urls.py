"""Stage gate API routes."""

from __future__ import annotations

from django.urls import path

from apps.stage_gates.api.decisions import (
    MajorGateDecisionView,
    ProposalReviewCycleView,
)
from apps.stage_gates.api.execution import (
    StageGateFirstLaunchFinalDecisionView,
    StageGateFirstLaunchManagementConclusionView,
    StageGateNormalDecisionView,
    StageGateSubmissionsView,
    StageGateValidateView,
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
    path(
        "stage-gates/<uuid:public_id>/validate",
        StageGateValidateView.as_view(),
        name="stage-gate-validate",
    ),
    path(
        "stage-gates/<uuid:public_id>/submissions",
        StageGateSubmissionsView.as_view(),
        name="stage-gate-submissions",
    ),
    path(
        "stage-gates/<uuid:public_id>/decision",
        StageGateNormalDecisionView.as_view(),
        name="stage-gate-decision",
    ),
    path(
        "stage-gates/<uuid:public_id>/first-launch-management-conclusion",
        StageGateFirstLaunchManagementConclusionView.as_view(),
        name="stage-gate-first-launch-management-conclusion",
    ),
    path(
        "stage-gates/<uuid:public_id>/first-launch-final-decision",
        StageGateFirstLaunchFinalDecisionView.as_view(),
        name="stage-gate-first-launch-final-decision",
    ),
]
