"""Execution stage-gate validate/submit/decision APIs."""

from __future__ import annotations

from typing import cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.models.user import User
from apps.platform.api.errors import ValidationFailedError
from apps.platform.application.command import CommandContext
from apps.stage_gates.services.record_first_launch_decision import RecordFirstLaunchDecision
from apps.stage_gates.services.record_normal_decision import RecordNormalGateDecision
from apps.stage_gates.services.submit_execution_gate import SubmitExecutionGate
from apps.stage_gates.services.validate_execution_gate import ValidateExecutionGate


class StageGateValidateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="stage_gates_validate")
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        result = ValidateExecutionGate(
            context=CommandContext.for_actor(user),
            stage_gate_public_id=public_id,
        ).execute()
        return Response({"blocks": result.blocks, "warnings": result.warnings})


class StageGateSubmissionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="stage_gates_submissions_create")
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        idempotency_key = str(request.data.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValidationFailedError(message="idempotency_key is required.")
        submission = SubmitExecutionGate(
            context=CommandContext.for_actor(user),
            stage_gate_public_id=public_id,
            idempotency_key=idempotency_key,
        ).execute()
        return Response(
            {
                "public_id": str(submission.public_id),
                "submission_number": submission.submission_number,
                "content_hash": submission.content_hash,
            },
            status=201,
        )


class StageGateNormalDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="stage_gates_decision_create")
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        result = str(request.data.get("result") or "")
        idempotency_key = str(request.data.get("idempotency_key") or "").strip()
        if not result or not idempotency_key:
            raise ValidationFailedError(message="result and idempotency_key are required.")
        decision = RecordNormalGateDecision(
            context=CommandContext.for_actor(user),
            stage_gate_public_id=public_id,
            result=result,
            decision_summary=str(request.data.get("decision_summary") or ""),
            idempotency_key=idempotency_key,
            exception_rationale=str(request.data.get("exception_rationale") or ""),
        ).execute()
        return Response(
            {
                "public_id": str(decision.public_id),
                "result": decision.result,
            },
            status=201,
        )


class StageGateFirstLaunchDecisionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(operation_id="stage_gates_first_launch_decision_create")
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        management_conclusion = str(request.data.get("management_conclusion") or "")
        final_decision = str(request.data.get("final_decision") or "")
        idempotency_key = str(request.data.get("idempotency_key") or "").strip()
        if not management_conclusion or not final_decision or not idempotency_key:
            raise ValidationFailedError(
                message="management_conclusion, final_decision, and idempotency_key are required."
            )
        result = RecordFirstLaunchDecision(
            context=CommandContext.for_actor(user),
            stage_gate_public_id=public_id,
            management_conclusion=management_conclusion,
            final_decision=final_decision,
            decision_summary=str(request.data.get("decision_summary") or ""),
            idempotency_key=idempotency_key,
        ).execute()
        return Response(
            {
                "decision_public_id": str(result.decision.public_id),
                "final_decision": result.decision.final_decision,
                "handover_error": result.handover_error,
                "project_status": (
                    result.handover.project.status if result.handover is not None else None
                ),
            },
            status=201,
        )
