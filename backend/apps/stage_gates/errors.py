"""Stable domain error codes for major stage gate decisions."""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class MajorGateRoleNotConfigured(ApiError):
    code = "MAJOR_GATE_ROLE_NOT_CONFIGURED"
    message = "The major stage gate decision roles are not configured."
    status_code = 409


class MajorGateMaterialChanged(ApiError):
    code = "MAJOR_GATE_MATERIAL_CHANGED"
    message = "The review material version has changed."
    status_code = 409


class MajorGateAlreadyDecided(ApiError):
    code = "MAJOR_GATE_ALREADY_DECIDED"
    message = "The stage gate has already been decided."
    status_code = 409


class MajorGateConclusionRequired(ApiError):
    code = "MAJOR_GATE_CONCLUSION_REQUIRED"
    message = "Both management conclusion and final decision are required."
    status_code = 400


class ReviewCycleNotStartable(ApiError):
    code = "REVIEW_CYCLE_NOT_STARTABLE"
    message = "The subject cannot enter a review cycle in its current state."
    status_code = 409


class GateSubmissionBlocked(ApiError):
    code = "GATE_SUBMISSION_BLOCKED"
    message = "The execution gate still has blocking items."
    status_code = 409


class GateAlreadyDecided(ApiError):
    code = "GATE_ALREADY_DECIDED"
    message = "The execution gate has already been decided."
    status_code = 409


class GateDecisionNotAllowed(ApiError):
    code = "GATE_DECISION_NOT_ALLOWED"
    message = "The requested gate decision is not allowed for this actor."
    status_code = 409


class DualControlSeparationRequired(ApiError):
    code = "DUAL_CONTROL_SEPARATION_REQUIRED"
    message = "The final decision must be recorded by a different actor than the conclusion author."
    status_code = 409
