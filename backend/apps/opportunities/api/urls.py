"""Opportunity API routes."""

from __future__ import annotations

from django.urls import path

from apps.opportunities.api.candidates import (
    ProjectCandidateAssessmentView,
    ProjectCandidateDetailView,
    ProjectCandidateLeadershipView,
    ProjectCandidateSourcesView,
    ProjectCandidateSplitView,
    ProjectCandidateSubmitReviewView,
)
from apps.opportunities.api.deferred import (
    DeferredItemDetailView,
    DeferredQuarterlyReviewView,
)
from apps.opportunities.api.lifecycle_board import LifecycleBoardView
from apps.opportunities.api.opportunities import (
    OpportunityCollectionView,
    OpportunityDetailView,
    OpportunityMemberInvitationAcceptView,
    OpportunityMemberInvitationDeclineView,
    OpportunityMemberInvitationView,
    OpportunityPoolView,
    OpportunitySubmitView,
    OpportunityVersionsView,
    OpportunityWithdrawView,
)
from apps.opportunities.api.proposal_quotas import CurrentProposalQuotaView
from apps.opportunities.api.reconsiderations import ReconsiderationCollectionView

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
        "opportunities/<uuid:public_id>/members/invitations/accept",
        OpportunityMemberInvitationAcceptView.as_view(),
        name="opportunity-member-invitation-accept",
    ),
    path(
        "opportunities/<uuid:public_id>/members/invitations/decline",
        OpportunityMemberInvitationDeclineView.as_view(),
        name="opportunity-member-invitation-decline",
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
    path(
        "project-candidates/<uuid:public_id>/sources",
        ProjectCandidateSourcesView.as_view(),
        name="project-candidate-sources",
    ),
    path(
        "project-candidates/<uuid:public_id>/split",
        ProjectCandidateSplitView.as_view(),
        name="project-candidate-split",
    ),
    path(
        "deferred-items/<uuid:public_id>/quarterly-review",
        DeferredQuarterlyReviewView.as_view(),
        name="deferred-quarterly-review",
    ),
    path(
        "deferred-items/<uuid:public_id>",
        DeferredItemDetailView.as_view(),
        name="deferred-item-detail",
    ),
    path(
        "reconsiderations",
        ReconsiderationCollectionView.as_view(),
        name="reconsideration-collection",
    ),
    path(
        "opportunity-pool",
        OpportunityPoolView.as_view(),
        name="opportunity-pool",
    ),
    path(
        "proposal-quotas/current",
        CurrentProposalQuotaView.as_view(),
        name="proposal-quotas-current",
    ),
    path(
        "lifecycle-board",
        LifecycleBoardView.as_view(),
        name="lifecycle-board",
    ),
]
