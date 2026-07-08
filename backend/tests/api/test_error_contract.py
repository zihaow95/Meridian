"""Contract tests for the unified API error response shape."""

from __future__ import annotations

import tempfile
from pathlib import Path

from rest_framework.test import APIClient


def test_hidden_resource_error_does_not_reveal_existence(api_client: APIClient) -> None:
    response = api_client.get("/api/v1/_test/hidden-resource")

    assert response.status_code == 404
    assert response.json()["code"] == "RESOURCE_NOT_FOUND"
    assert set(response.json()) == {"code", "message", "details", "trace_id"}


def test_hidden_resource_test_endpoint_is_excluded_from_openapi_schema() -> None:
    from django.core.management import call_command

    scratch_root = Path(__file__).resolve().parents[2] / "var" / "pytest-scratch"
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root) as tmp:
        schema_path = Path(tmp) / "schema.yaml"
        call_command("spectacular", file=str(schema_path), validate=True)

        schema_text = schema_path.read_text(encoding="utf-8")
        assert "/api/v1/_test/hidden-resource" not in schema_text
