"""Dual-control administrative change rules."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.authorization.models.admin_change import AdminChangeRequest, AdminChangeStatus
from apps.authorization.services.request_admin_change import RequestAdminChange
from apps.authorization.services.review_admin_change import (
    AdminChangeNotPending,
    AdminChangeReviewDenied,
    ReviewAdminChange,
    ReviewerMustDiffer,
)
from apps.platform.application.command import CommandContext


@pytest.fixture
def change_request(active_user, another_active_user, grant_action) -> AdminChangeRequest:
    grant_action(
        active_user, "authorization.admin_change.request", "authorization.admin_change_request"
    )
    context = CommandContext.for_actor(active_user)
    return RequestAdminChange(
        context=context,
        action_type="authorization.role.assign",
        target_summary={"role_code": "SYSTEM_ADMIN"},
        before_summary={},
        after_summary={"role_code": "SYSTEM_ADMIN"},
        expires_in=timedelta(days=1),
    ).execute()


@pytest.mark.django_db
def test_proposer_cannot_review_own_admin_change(change_request, active_user) -> None:
    with pytest.raises(ReviewerMustDiffer):
        ReviewAdminChange(actor=change_request.proposed_by, request=change_request).approve()
    change_request.refresh_from_db()
    assert change_request.status == AdminChangeStatus.PENDING


@pytest.mark.django_db
def test_reviewer_can_approve_pending_change(
    change_request, another_active_user, grant_action
) -> None:
    grant_action(
        another_active_user,
        "authorization.admin_change.review",
        "authorization.admin_change_request",
    )
    ReviewAdminChange(actor=another_active_user, request=change_request).approve()
    change_request.refresh_from_db()
    assert change_request.status == AdminChangeStatus.APPROVED
    assert change_request.reviewed_by_id == another_active_user.pk


@pytest.mark.django_db
def test_reviewer_without_permission_cannot_approve_admin_change(
    change_request, another_active_user
) -> None:
    with pytest.raises(AdminChangeReviewDenied):
        ReviewAdminChange(actor=another_active_user, request=change_request).approve()

    change_request.refresh_from_db()
    assert change_request.status == AdminChangeStatus.PENDING


@pytest.mark.django_db
def test_expired_request_cannot_be_reviewed(
    change_request, another_active_user, grant_action
) -> None:
    grant_action(
        another_active_user,
        "authorization.admin_change.review",
        "authorization.admin_change_request",
    )
    change_request.expires_at = timezone.now() - timedelta(minutes=1)
    change_request.save(update_fields=["expires_at", "updated_at"])
    with pytest.raises(AdminChangeNotPending):
        ReviewAdminChange(actor=another_active_user, request=change_request).approve()
