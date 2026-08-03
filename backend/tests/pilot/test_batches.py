"""Pilot batch creation freezes config on start and blocks P0/P1 completion."""

from __future__ import annotations

import pytest

from apps.pilot.errors import BatchCompletionBlocked, PilotValidationError
from apps.pilot.models import PilotBatchPurpose, PilotBatchStatus, PilotFeedbackSeverity
from apps.pilot.services.batches import (
    AddPilotParticipant,
    CompletePilotBatch,
    CreatePilotBatch,
    StartPilotBatch,
)
from apps.pilot.services.feedback import AssignPilotFeedback, OpenPilotFeedback
from apps.platform.application.command import CommandContext

pytestmark = pytest.mark.django_db


def test_create_batch_uses_editable_defaults_not_hardcoded_business_rule(
    active_user,
) -> None:
    batch = CreatePilotBatch(
        context=CommandContext.for_actor(active_user),
        name="Internal acceptance A",
        planned_participant_count=3,
        planned_duration_days=5,
    ).execute()

    assert batch.planned_participant_count == 3
    assert batch.planned_duration_days == 5
    assert batch.purpose == PilotBatchPurpose.INTERNAL_ACCEPTANCE
    assert batch.status == PilotBatchStatus.DRAFT
    assert batch.config_snapshot == {}


def test_start_freezes_participant_snapshot_against_later_template_edits(
    active_user, another_active_user
) -> None:
    ctx = CommandContext.for_actor(active_user)
    batch = CreatePilotBatch(context=ctx, name="Snap").execute()
    AddPilotParticipant(
        context=ctx,
        batch_public_id=batch.public_id,
        user_public_id=another_active_user.public_id,
        department_snapshot="QA",
    ).execute()
    StartPilotBatch(context=ctx, batch_public_id=batch.public_id).execute()
    batch.refresh_from_db()

    assert batch.status == PilotBatchStatus.OPEN
    assert batch.config_snapshot["planned_participant_count"] == 8
    assert batch.config_snapshot["participants"][0]["department"] == "QA"

    batch.planned_participant_count = 99
    batch.save(update_fields=["planned_participant_count", "updated_at"])
    batch.refresh_from_db()
    assert batch.config_snapshot["planned_participant_count"] == 8


def test_complete_blocked_while_p0_open(active_user, another_active_user) -> None:
    ctx = CommandContext.for_actor(active_user)
    batch = CreatePilotBatch(context=ctx, name="Block").execute()
    AddPilotParticipant(
        context=ctx,
        batch_public_id=batch.public_id,
        user_public_id=another_active_user.public_id,
    ).execute()
    StartPilotBatch(context=ctx, batch_public_id=batch.public_id).execute()
    feedback = OpenPilotFeedback(
        context=ctx,
        batch_public_id=batch.public_id,
        title="Crash",
        reproduction_summary="Click save",
    ).execute()
    AssignPilotFeedback(
        context=ctx,
        feedback_public_id=feedback.public_id,
        severity=PilotFeedbackSeverity.P0,
        assignee_public_id=another_active_user.public_id,
    ).execute()

    with pytest.raises(BatchCompletionBlocked):
        CompletePilotBatch(context=ctx, batch_public_id=batch.public_id).execute()


def test_phase6_rejects_business_pilot_purpose(active_user) -> None:
    with pytest.raises(PilotValidationError, match="INTERNAL_ACCEPTANCE"):
        CreatePilotBatch(
            context=CommandContext.for_actor(active_user),
            name="Real business",
            purpose=PilotBatchPurpose.BUSINESS_PILOT,
        ).execute()
