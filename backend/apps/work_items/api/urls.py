"""Work-item API routes."""

from __future__ import annotations

from django.urls import path

from apps.work_items.api.deliverables import (
    DeliverableRevisionSubmitView,
    DeliverableRevisionsView,
    ProfessionalConfirmationDecideView,
)
from apps.work_items.api.tasks import TaskAssignView, TaskTransitionView, TaskUpdateView

urlpatterns = [
    path("tasks/<uuid:public_id>", TaskUpdateView.as_view(), name="tasks-update"),
    path(
        "tasks/<uuid:public_id>/transition",
        TaskTransitionView.as_view(),
        name="tasks-transition",
    ),
    path("tasks/<uuid:public_id>/assign", TaskAssignView.as_view(), name="tasks-assign"),
    path(
        "deliverables/<uuid:public_id>/revisions",
        DeliverableRevisionsView.as_view(),
        name="deliverables-revisions-create",
    ),
    path(
        "deliverable-revisions/<uuid:public_id>/submit",
        DeliverableRevisionSubmitView.as_view(),
        name="deliverable-revisions-submit",
    ),
    path(
        "professional-confirmations/<uuid:public_id>/decide",
        ProfessionalConfirmationDecideView.as_view(),
        name="professional-confirmations-decide",
    ),
]
