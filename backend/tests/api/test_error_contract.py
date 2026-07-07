"""Contract tests for the unified API error response shape."""

from __future__ import annotations

from rest_framework.test import APIClient


def test_hidden_resource_error_does_not_reveal_existence(api_client: APIClient) -> None:
    response = api_client.get("/api/v1/_test/hidden-resource")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert set(response.json()) == {"code", "message", "details", "trace_id"}
