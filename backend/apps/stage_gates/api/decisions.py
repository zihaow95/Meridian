"""Major stage gate API: open review cycle and record decision."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.opportunities.api.schemas import (
    MAJOR_GATE_DECISION_REQUEST_SCHEMA,
    MAJOR_GATE_DECISION_RESPONSE_SCHEMA,
    STAGE_GATE_SUMMARY_SCHEMA,
)
from apps.platform.application.command import CommandContext
from apps.stage_gates.models import MajorGateDecision, StageGateInstance
from apps.stage_gates.services.create_review_cycle import CreateProposalReviewCycle
from apps.stage_gates.services.record_major_decision import RecordMajorGateDecision


def _serialize_gate(gate: StageGateInstance) -> dict[str, object]:
    return {
        "public_id": str(gate.public_id),
        "stage_code": gate.stage_code,
        "cycle_number": gate.cycle_number,
        "status": gate.status,
        "subject_type": gate.subject_type,
        "subject_public_id": str(gate.subject_public_id),
    }


def _serialize_decision(decision: MajorGateDecision) -> dict[str, object]:
    return {
        "public_id": str(decision.public_id),
        "stage_gate_public_id": str(decision.stage_gate.public_id),
        "management_conclusion": decision.management_conclusion,
        "final_decision": decision.final_decision,
        "has_conclusion_difference": decision.has_conclusion_difference,
        "decision_summary": decision.decision_summary,
    }


class ProposalReviewCycleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="opportunity_review_cycle_create",
        request=None,
        responses={201: STAGE_GATE_SUMMARY_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        gate = CreateProposalReviewCycle(
            context=CommandContext.for_actor(user),
            opportunity_public_id=public_id,
        ).execute()
        return Response(_serialize_gate(gate), status=201)


class MajorGateDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="stage_gate_major_decision_create",
        request=MAJOR_GATE_DECISION_REQUEST_SCHEMA,
        responses={201: MAJOR_GATE_DECISION_RESPONSE_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        data = request.data
        decision = RecordMajorGateDecision(
            context=CommandContext.for_actor(user),
            stage_gate_public_id=public_id,
            management_conclusion=str(data.get("management_conclusion", "")),
            final_decision=str(data.get("final_decision", "")),
            decision_summary=str(data.get("decision_summary", "")),
            idempotency_key=str(data.get("idempotency_key", "")),
            defer_reason=str(data.get("defer_reason", "")),
            restart_trigger=str(data.get("restart_trigger", "")),
            next_review_quarter=str(data.get("next_review_quarter", "")),
        ).execute()
        return Response(_serialize_decision(decision), status=201)
