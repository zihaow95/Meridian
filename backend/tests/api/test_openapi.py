"""Contract test for the generated OpenAPI schema.

The schema must be generatable, describe API version v1, and expose the health
endpoint. This guards the contract source the frontend types are generated from.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.generators import SchemaGenerator


def _generate_schema() -> dict[str, Any]:
    generator = SchemaGenerator()
    return generator.get_schema(request=None, public=True)


def test_schema_declares_api_version_v1() -> None:
    schema = _generate_schema()

    assert schema["openapi"].startswith("3.")
    assert schema["info"]["version"] == "v1"


def test_schema_exposes_health_endpoint() -> None:
    schema = _generate_schema()

    assert "/api/v1/health" in schema["paths"]
    assert "get" in schema["paths"]["/api/v1/health"]
