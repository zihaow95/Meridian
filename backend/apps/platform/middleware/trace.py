"""Attach a trace identifier to every request/response cycle."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from apps.platform.request_context import generate_trace_id, set_trace_id


class TraceIdMiddleware:
    header_name = "X-Trace-Id"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(self.header_name)
        trace_id = incoming if incoming else generate_trace_id()
        set_trace_id(trace_id)
        request.trace_id = trace_id  # type: ignore[attr-defined]
        response = self.get_response(request)
        response[self.header_name] = trace_id
        return response
