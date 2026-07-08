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
