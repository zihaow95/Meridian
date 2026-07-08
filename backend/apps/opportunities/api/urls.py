"""Opportunity API routes."""

from __future__ import annotations

from django.urls import path

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
]
