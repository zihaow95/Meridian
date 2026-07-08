"""Opportunity API routes."""

from __future__ import annotations

from django.urls import path

from apps.opportunities.api.candidates import (
    ProjectCandidateAssessmentView,
    ProjectCandidateDetailView,
    ProjectCandidateLeadershipView,
    ProjectCandidateSubmitReviewView,
)
from apps.opportunities.api.opportunities import (
    OpportunityCollectionView,
    OpportunityDetailView,
    OpportunityMemberInvitationView,
    OpportunitySubmitView,
    OpportunityVersionsView,
    OpportunityWithdrawView,
)

urlpatterns = [
    path(
        "opportunities",
        OpportunityCollectionView.as_view(),
        name="opportunity-collection",
    ),
    path(
        "opportunities/<uuid:public_id>",
        OpportunityDetailView.as_view(),
        name="opportunity-detail",
    ),
    path(
        "opportunities/<uuid:public_id>/members/invitations",
        OpportunityMemberInvitationView.as_view(),
        name="opportunity-member-invitations",
    ),
    path(
        "opportunities/<uuid:public_id>/submit",
        OpportunitySubmitView.as_view(),
        name="opportunity-submit",
    ),
    path(
        "opportunities/<uuid:public_id>/withdraw",
        OpportunityWithdrawView.as_view(),
        name="opportunity-withdraw",
    ),
    path(
        "opportunities/<uuid:public_id>/versions",
        OpportunityVersionsView.as_view(),
        name="opportunity-versions",
    ),
    path(
        "project-candidates/<uuid:public_id>",
        ProjectCandidateDetailView.as_view(),
        name="project-candidate-detail",
    ),
    path(
        "project-candidates/<uuid:public_id>/leadership",
        ProjectCandidateLeadershipView.as_view(),
        name="project-candidate-leadership",
    ),
    path(
        "project-candidates/<uuid:public_id>/assessments/<str:category_code>",
        ProjectCandidateAssessmentView.as_view(),
        name="project-candidate-assessment",
    ),
    path(
        "project-candidates/<uuid:public_id>/submit-review",
        ProjectCandidateSubmitReviewView.as_view(),
        name="project-candidate-submit-review",
    ),
]
