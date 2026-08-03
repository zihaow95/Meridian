"""Feedback moves OPEN→TRIAGED→IN_PROGRESS→READY_FOR_RETEST→CLOSED with version guards."""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from apps.pilot.errors import FeedbackVersionConflict, PilotValidationError
from apps.pilot.models import PilotFeedback, PilotFeedbackSeverity, PilotFeedbackStatus
from apps.pilot.services.batches import AddPilotParticipant, CreatePilotBatch, StartPilotBatch
from apps.pilot.services.feedback import (
    AssignPilotFeedback,
    ClosePilotFeedback,
    OpenPilotFeedback,
    RetestPilotFeedback,
    StartFeedbackHandling,
    SubmitFeedbackRetest,
)
from apps.platform.application.command import CommandContext

pytestmark = pytest.mark.django_db


@pytest.fixture
def open_batch(active_user, another_active_user):
    ctx = CommandContext.for_actor(active_user)
    batch = CreatePilotBatch(context=ctx, name="Lifecycle").execute()
    AddPilotParticipant(
        context=ctx,
        batch_public_id=batch.public_id,
        user_public_id=another_active_user.public_id,
    ).execute()
    return StartPilotBatch(context=ctx, batch_public_id=batch.public_id).execute()


def _full_happy_path(ctx, batch, assignee, *, severity=PilotFeedbackSeverity.P1):
    feedback = OpenPilotFeedback(
        context=ctx,
        batch_public_id=batch.public_id,
        title="Broken filter",
        reproduction_summary="Open list and click filter",
        external_key="ext-1",
    ).execute()
    feedback = AssignPilotFeedback(
        context=ctx,
        feedback_public_id=feedback.public_id,
        severity=severity,
        assignee_public_id=assignee.public_id,
        expected_version=feedback.version_no,
    ).execute()
    feedback = StartFeedbackHandling(
        context=ctx,
        feedback_public_id=feedback.public_id,
        expected_version=feedback.version_no,
    ).execute()
    feedback = SubmitFeedbackRetest(
        context=ctx,
        feedback_public_id=feedback.public_id,
        target_version="0.6.1",
        expected_version=feedback.version_no,
    ).execute()
    feedback = RetestPilotFeedback(
        context=ctx,
        feedback_public_id=feedback.public_id,
        passed=True,
        expected_version=feedback.version_no,
    ).execute()
    return ClosePilotFeedback(
        context=ctx,
        feedback_public_id=feedback.public_id,
        expected_version=feedback.version_no,
    ).execute()


def test_happy_path_closes_after_passed_retest(active_user, another_active_user, open_batch):
    ctx = CommandContext.for_actor(active_user)
    closed = _full_happy_path(ctx, open_batch, another_active_user)
    assert closed.status == PilotFeedbackStatus.CLOSED
    assert closed.retest_result == "PASSED"


def test_external_key_is_idempotent(active_user, open_batch):
    ctx = CommandContext.for_actor(active_user)
    first = OpenPilotFeedback(
        context=ctx,
        batch_public_id=open_batch.public_id,
        title="A",
        reproduction_summary="steps",
        external_key="dup-key",
    ).execute()
    second = OpenPilotFeedback(
        context=ctx,
        batch_public_id=open_batch.public_id,
        title="B",
        reproduction_summary="other",
        external_key="dup-key",
    ).execute()
    assert first.public_id == second.public_id
    assert PilotFeedback.objects.filter(batch=open_batch, external_key="dup-key").count() == 1


def test_mysql_rejects_duplicate_external_key_slot(active_user, open_batch):
    PilotFeedback.objects.create(
        organization_id=active_user.organization_id,
        batch=open_batch,
        reporter=active_user,
        title="One",
        reproduction_summary="a",
        external_key="slot-key",
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            row = PilotFeedback(
                organization_id=active_user.organization_id,
                batch=open_batch,
                reporter=active_user,
                title="Two",
                reproduction_summary="b",
                external_key="slot-key",
            )
            # Bypass save() slot logic to prove the DB constraint itself.
            PilotFeedback.objects.bulk_create(
                [
                    PilotFeedback(
                        organization_id=row.organization_id,
                        batch=row.batch,
                        reporter=row.reporter,
                        title=row.title,
                        reproduction_summary=row.reproduction_summary,
                        external_key="slot-key",
                        external_key_slot=1,
                    )
                ]
            )


def test_stale_version_on_assign_conflicts(active_user, another_active_user, open_batch):
    ctx = CommandContext.for_actor(active_user)
    feedback = OpenPilotFeedback(
        context=ctx,
        batch_public_id=open_batch.public_id,
        title="Race",
        reproduction_summary="steps",
    ).execute()
    AssignPilotFeedback(
        context=ctx,
        feedback_public_id=feedback.public_id,
        severity=PilotFeedbackSeverity.P2,
        assignee_public_id=another_active_user.public_id,
        expected_version=feedback.version_no,
    ).execute()
    with pytest.raises(FeedbackVersionConflict):
        AssignPilotFeedback(
            context=ctx,
            feedback_public_id=feedback.public_id,
            severity=PilotFeedbackSeverity.P1,
            assignee_public_id=another_active_user.public_id,
            expected_version=feedback.version_no,
        ).execute()


def test_p2_leftover_requires_acceptance_fields(
    active_user, another_active_user, open_batch
):
    ctx = CommandContext.for_actor(active_user)
    feedback = OpenPilotFeedback(
        context=ctx,
        batch_public_id=open_batch.public_id,
        title="P2",
        reproduction_summary="steps",
    ).execute()
    AssignPilotFeedback(
        context=ctx,
        feedback_public_id=feedback.public_id,
        severity=PilotFeedbackSeverity.P2,
        assignee_public_id=another_active_user.public_id,
    ).execute()
    feedback.refresh_from_db()

    with pytest.raises(PilotValidationError, match="workaround"):
        ClosePilotFeedback(
            context=ctx,
            feedback_public_id=feedback.public_id,
            expected_version=feedback.version_no,
        ).execute()

    closed = ClosePilotFeedback(
        context=ctx,
        feedback_public_id=feedback.public_id,
        workaround="Use alternate path",
        target_version="0.7.0",
        accepted_by_public_id=active_user.public_id,
        acceptance_note="Accepted for internal acceptance batch",
        expected_version=feedback.version_no,
    ).execute()
    assert closed.status == PilotFeedbackStatus.CLOSED
    assert closed.accepted_by_id == active_user.id
