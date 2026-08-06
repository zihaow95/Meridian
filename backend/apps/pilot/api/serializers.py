"""Shared serialization helpers for pilot APIs."""

from __future__ import annotations

from typing import Any

from apps.pilot.models import PilotBatch, PilotFeedback, PilotParticipant


def serialize_batch(batch: PilotBatch) -> dict[str, Any]:
    return {
        "public_id": str(batch.public_id),
        "name": batch.name,
        "purpose": batch.purpose,
        "status": batch.status,
        "planned_participant_count": batch.planned_participant_count,
        "planned_duration_days": batch.planned_duration_days,
        "config_snapshot": batch.config_snapshot,
        "data_scope_note": batch.data_scope_note,
        "feedback_owner_note": batch.feedback_owner_note,
        "version_no": batch.version_no,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
    }


def serialize_participant(participant: PilotParticipant) -> dict[str, Any]:
    return {
        "public_id": str(participant.public_id),
        "user_public_id": str(participant.user.public_id),
        "display_name_snapshot": participant.display_name_snapshot,
        "employee_no_snapshot": participant.employee_no_snapshot,
        "department_snapshot": participant.department_snapshot,
        "role_codes_snapshot": participant.role_codes_snapshot,
    }


def serialize_feedback(feedback: PilotFeedback) -> dict[str, Any]:
    return {
        "public_id": str(feedback.public_id),
        "batch_public_id": str(feedback.batch.public_id),
        "title": feedback.title,
        "reproduction_summary": feedback.reproduction_summary,
        "severity": feedback.severity,
        "status": feedback.status,
        "external_key": feedback.external_key,
        "evidence_document_version_public_id": (
            str(feedback.evidence_document_version_public_id)
            if feedback.evidence_document_version_public_id
            else None
        ),
        "assignee_public_id": (
            str(feedback.assignee.public_id) if feedback.assignee is not None else None
        ),
        "target_version": feedback.target_version,
        "workaround": feedback.workaround,
        "accepted_by_public_id": (
            str(feedback.accepted_by.public_id) if feedback.accepted_by is not None else None
        ),
        "acceptance_note": feedback.acceptance_note,
        "close_reason": feedback.close_reason,
        "retest_result": feedback.retest_result,
        "version_no": feedback.version_no,
    }
