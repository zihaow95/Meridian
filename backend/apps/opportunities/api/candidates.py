"""Project candidate API: read, leadership, assessment edits, submit review."""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.authorization.context import AuthorizationContext, ResourceDescriptor
from apps.authorization.policies.engine import authorize
from apps.authorization.services.subject import subject_for
from apps.identity.models.user import User
from apps.opportunities.api.schemas import (
    ASSESSMENT_UPDATE_REQUEST_SCHEMA,
    ASSIGN_LEADERSHIP_REQUEST_SCHEMA,
    CANDIDATE_SPLIT_LIST_SCHEMA,
    CASE_ASSESSMENT_SCHEMA,
    COMBINE_SOURCES_REQUEST_SCHEMA,
    PROJECT_CANDIDATE_DETAIL_SCHEMA,
    SPLIT_CANDIDATE_REQUEST_SCHEMA,
    SUBMIT_CANDIDATE_REVIEW_REQUEST_SCHEMA,
)
from apps.opportunities.models import ProjectCandidate
from apps.opportunities.queries.candidates import serialize_candidate_detail
from apps.opportunities.services.assign_case_leadership import AssignCaseLeadership
from apps.opportunities.services.combine_candidate_sources import CombineCandidateSources
from apps.opportunities.services.split_project_candidate import SplitProjectCandidate
from apps.opportunities.services.submit_project_review import SubmitProjectReview
from apps.opportunities.services.update_assessment import UpdateCaseAssessment
from apps.platform.api.errors import ResourceNotFoundError, ValidationFailedError
from apps.platform.application.command import CommandContext


def _uuid(value: Any, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise ValidationFailedError(message=f"Invalid {field}.") from exc


def _optional_uuid(value: Any, field: str) -> UUID | None:
    if value in (None, ""):
        return None
    return _uuid(value, field)


def _can(user: User, action: str, candidate: ProjectCandidate) -> bool:
    return authorize(
        subject_for(user),
        action=action,
        resource=ResourceDescriptor(
            resource_type="project_candidate",
            public_id=candidate.public_id,
            organization_id=candidate.organization_id,
        ),
        context=AuthorizationContext.current(),
    ).allowed


def _load(user: User, public_id: UUID) -> ProjectCandidate:
    candidate = ProjectCandidate.objects.filter(
        public_id=public_id,
        organization_id=user.organization_id,
    ).first()
    if candidate is None:
        raise ResourceNotFoundError()
    return candidate


class ProjectCandidateDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_candidates_retrieve",
        responses=PROJECT_CANDIDATE_DETAIL_SCHEMA,
    )
    def get(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        candidate = _load(user, public_id)
        readable = (
            candidate.case_owner_id == user.id
            or candidate.deputy_leader_id == user.id
            or _can(user, "candidate.leadership.assign", candidate)
            or _can(user, "candidate.assessment.edit", candidate)
        )
        if not readable:
            raise ResourceNotFoundError()
        return Response(serialize_candidate_detail(candidate))


class ProjectCandidateLeadershipView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_candidates_leadership_create",
        request=ASSIGN_LEADERSHIP_REQUEST_SCHEMA,
        responses=PROJECT_CANDIDATE_DETAIL_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        data = request.data
        version_no = data.get("version_no")
        candidate = AssignCaseLeadership(
            context=CommandContext.for_actor(user),
            candidate_public_id=public_id,
            version_no=int(version_no) if version_no is not None else -1,
            case_owner_public_id=_uuid(data.get("case_owner_public_id"), "case_owner_public_id"),
            deputy_leader_public_id=_optional_uuid(
                data.get("deputy_leader_public_id"), "deputy_leader_public_id"
            ),
        ).execute()
        return Response(serialize_candidate_detail(candidate))


class ProjectCandidateAssessmentView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_candidates_assessments_partial_update",
        request=ASSESSMENT_UPDATE_REQUEST_SCHEMA,
        responses=CASE_ASSESSMENT_SCHEMA,
    )
    def patch(self, request: Request, public_id: UUID, category_code: str) -> Response:
        user = cast(User, request.user)
        data = request.data
        assessment = UpdateCaseAssessment(
            context=CommandContext.for_actor(user),
            candidate_public_id=public_id,
            category_code=category_code,
            conclusion=(str(data["conclusion"]) if "conclusion" in data else None),
            status=(str(data["status"]) if "status" in data else None),
            deliverable_version_public_id=_optional_uuid(
                data.get("deliverable_version_public_id"),
                "deliverable_version_public_id",
            ),
        ).execute()
        return Response(
            {
                "category_code": assessment.category_code,
                "status": assessment.status,
                "conclusion": assessment.conclusion,
            }
        )


class ProjectCandidateSubmitReviewView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_candidates_submit_review_create",
        request=SUBMIT_CANDIDATE_REVIEW_REQUEST_SCHEMA,
        responses=PROJECT_CANDIDATE_DETAIL_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        data = request.data
        version_no = data.get("version_no")
        candidate = SubmitProjectReview(
            context=CommandContext.for_actor(user),
            candidate_public_id=public_id,
            version_no=int(version_no) if version_no is not None else -1,
            idempotency_key=str(data.get("idempotency_key", "")),
            proposed_schedule=(
                data.get("proposed_schedule")
                if isinstance(data.get("proposed_schedule"), dict)
                else None
            ),
            resource_risk_summary=(
                str(data["resource_risk_summary"]) if "resource_risk_summary" in data else None
            ),
        ).execute()
        return Response(serialize_candidate_detail(candidate))


class ProjectCandidateSourcesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_candidates_sources_create",
        request=COMBINE_SOURCES_REQUEST_SCHEMA,
        responses=PROJECT_CANDIDATE_DETAIL_SCHEMA,
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        raw_ids = request.data.get("opportunity_public_ids", [])
        if not isinstance(raw_ids, list):
            raise ValidationFailedError(message="opportunity_public_ids must be a list.")
        opportunity_ids = [_uuid(item, "opportunity_public_id") for item in raw_ids]
        candidate = CombineCandidateSources(
            context=CommandContext.for_actor(user),
            candidate_public_id=public_id,
            opportunity_public_ids=opportunity_ids,
        ).execute()
        return Response(serialize_candidate_detail(candidate))


class ProjectCandidateSplitView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        operation_id="project_candidates_split_create",
        request=SPLIT_CANDIDATE_REQUEST_SCHEMA,
        responses={201: CANDIDATE_SPLIT_LIST_SCHEMA},
    )
    def post(self, request: Request, public_id: UUID) -> Response:
        user = cast(User, request.user)
        raw_names = request.data.get("candidate_names", [])
        if not isinstance(raw_names, list):
            raise ValidationFailedError(message="candidate_names must be a list.")
        names = [str(name) for name in raw_names if str(name).strip()]
        created = SplitProjectCandidate(
            context=CommandContext.for_actor(user),
            opportunity_public_id=public_id,
            candidate_names=names,
        ).execute()
        return Response(
            [{"public_id": str(c.public_id), "name": c.name} for c in created],
            status=201,
        )
