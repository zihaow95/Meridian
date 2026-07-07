"""Stable API error codes and exception types."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """Base class for intentional API failures with a stable response shape."""

    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."
    status_code: int = 500

    def __init__(
        self,
        *,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.message)
        self.message = message or self.message
        self.details = details or {}


class ResourceNotFoundError(ApiError):
    code = "RESOURCE_NOT_FOUND"
    message = "The requested resource was not found."
    status_code = 404


class PermissionDeniedError(ApiError):
    """Returned as 404 to avoid leaking object existence."""

    code = "RESOURCE_NOT_FOUND"
    message = "The requested resource was not found."
    status_code = 404


class ValidationFailedError(ApiError):
    code = "VALIDATION_FAILED"
    message = "The request could not be validated."
    status_code = 400


class UserNotActiveError(ApiError):
    code = "USER_NOT_ACTIVE"
    message = "The user account is not active."
    status_code = 403


class AuthenticationFailedError(ApiError):
    code = "AUTHENTICATION_FAILED"
    message = "Authentication failed."
    status_code = 401
