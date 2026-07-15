"""Work-item API routes."""

from __future__ import annotations

from django.urls import path

from apps.work_items.api.deliverables import (
    DeliverableRevisionsView,
    ProfessionalConfirmationDecideView,
)
from apps.work_items.api.tasks import TaskAssignView, TaskUpdateView

urlpatterns = [
    path("tasks/<uuid:public_id>", TaskUpdateView.as_view(), name="tasks-update"),
    path("tasks/<uuid:public_id>/assign", TaskAssignView.as_view(), name="tasks-assign"),
    path(
        "deliverables/<uuid:public_id>/revisions",
        DeliverableRevisionsView.as_view(),
        name="deliverables-revisions-create",
    ),
    path(
        "professional-confirmations/<uuid:public_id>/decide",
        ProfessionalConfirmationDecideView.as_view(),
        name="professional-confirmations-decide",
    ),
]
