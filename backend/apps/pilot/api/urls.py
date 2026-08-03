"""Pilot API routes."""

from __future__ import annotations

from django.urls import path

from apps.pilot.api.batches import (
    PilotBatchCompleteView,
    PilotBatchDetailView,
    PilotBatchListCreateView,
    PilotBatchParticipantView,
    PilotBatchStartView,
)
from apps.pilot.api.feedback import (
    PilotFeedbackAssignView,
    PilotFeedbackCloseView,
    PilotFeedbackHandleView,
    PilotFeedbackListCreateView,
    PilotFeedbackRetestSubmitView,
    PilotFeedbackRetestView,
)

urlpatterns = [
    path("pilot/batches", PilotBatchListCreateView.as_view(), name="pilot-batches"),
    path(
        "pilot/batches/<uuid:public_id>",
        PilotBatchDetailView.as_view(),
        name="pilot-batch-detail",
    ),
    path(
        "pilot/batches/<uuid:public_id>/participants",
        PilotBatchParticipantView.as_view(),
        name="pilot-batch-participants",
    ),
    path(
        "pilot/batches/<uuid:public_id>/start",
        PilotBatchStartView.as_view(),
        name="pilot-batch-start",
    ),
    path(
        "pilot/batches/<uuid:public_id>/complete",
        PilotBatchCompleteView.as_view(),
        name="pilot-batch-complete",
    ),
    path(
        "pilot/batches/<uuid:batch_public_id>/feedback",
        PilotFeedbackListCreateView.as_view(),
        name="pilot-batch-feedback",
    ),
    path(
        "pilot/feedback/<uuid:public_id>/assign",
        PilotFeedbackAssignView.as_view(),
        name="pilot-feedback-assign",
    ),
    path(
        "pilot/feedback/<uuid:public_id>/handle",
        PilotFeedbackHandleView.as_view(),
        name="pilot-feedback-handle",
    ),
    path(
        "pilot/feedback/<uuid:public_id>/submit-retest",
        PilotFeedbackRetestSubmitView.as_view(),
        name="pilot-feedback-submit-retest",
    ),
    path(
        "pilot/feedback/<uuid:public_id>/retest",
        PilotFeedbackRetestView.as_view(),
        name="pilot-feedback-retest",
    ),
    path(
        "pilot/feedback/<uuid:public_id>/close",
        PilotFeedbackCloseView.as_view(),
        name="pilot-feedback-close",
    ),
]
