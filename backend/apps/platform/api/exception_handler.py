"""DRF exception handler producing the unified error contract."""

from __future__ import annotations

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import status
from rest_framework.exceptions import APIException, NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from apps.platform.api.errors import ApiError, PermissionDeniedError, ResourceNotFoundError
from apps.platform.request_context import get_or_create_trace_id

logger = logging.getLogger(__name__)


def _error_body(code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "details": details,
        "trace_id": get_or_create_trace_id(),
    }


def custom_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, ApiError):
        return Response(
            _error_body(exc.code, exc.message, exc.details),
            status=exc.status_code,
        )

    if isinstance(exc, Http404 | NotFound):
        not_found = ResourceNotFoundError()
        return Response(
            _error_body(not_found.code, not_found.message, not_found.details),
            status=not_found.status_code,
        )

    if isinstance(exc, PermissionDenied):
        hidden = PermissionDeniedError()
        return Response(
            _error_body(hidden.code, hidden.message, hidden.details),
            status=hidden.status_code,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        if isinstance(exc, ValidationError):
            details: dict[str, Any] = {"fields": response.data}
            return Response(
                _error_body("VALIDATION_FAILED", "The request could not be validated.", details),
                status=status.HTTP_400_BAD_REQUEST,
            )

        if isinstance(exc, APIException):
            code = getattr(exc, "default_code", "REQUEST_FAILED")
            if isinstance(code, str):
                code = code.upper()
            else:
                code = "REQUEST_FAILED"
            details = {"detail": response.data}
            return Response(
                _error_body(code, str(exc.detail), details),
                status=response.status_code,
            )

    logger.exception("Unhandled API exception", exc_info=exc)
    return Response(
        _error_body("INTERNAL_ERROR", "An unexpected error occurred.", {}),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
