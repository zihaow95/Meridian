"""Phase 5 OpenAPI path contract for operations APIs."""

from __future__ import annotations

from typing import Any

from drf_spectacular.generators import SchemaGenerator

REQUIRED_PATH_METHODS: dict[str, set[str]] = {
    "/api/v1/operating-data-sources": {"get", "post"},
    "/api/v1/operating-data-sources/{public_id}/publish": {"post"},
    "/api/v1/operating-metrics": {"get", "post"},
    "/api/v1/operating-metrics/{public_id}/publish": {"post"},
    "/api/v1/risk-rules": {"get", "post"},
    "/api/v1/risk-rules/{public_id}/publish": {"post"},
    "/api/v1/operating-data/batches": {"post"},
    "/api/v1/operating-data/batches/{public_id}": {"get"},
    "/api/v1/operating-data/batches/{public_id}/confirm": {"post"},
    "/api/v1/operating-data/batches/{public_id}/retry": {"post"},
    "/api/v1/operating-data/batches/{public_id}/rows": {"get"},
    "/api/v1/operating-data/batches/{public_id}/validate": {"post"},
    "/api/v1/operating-data/unmapped": {"get"},
    "/api/v1/operating-data/snapshots": {"post"},
    "/api/v1/operating-values/overrides": {"post"},
    "/api/v1/operating-values/overrides/{public_id}/revoke": {"post"},
    "/api/v1/products/{public_id}/operating-summary": {"get"},
    "/api/v1/skus/{public_id}/operating-summary": {"get"},
    "/api/v1/operating-metrics/recalculate": {"post"},
    "/api/v1/risk-signals": {"get"},
    "/api/v1/risk-signals/{public_id}/view": {"post"},
    "/api/v1/risk-signals/{public_id}/close": {"post"},
    "/api/v1/risk-signals/{public_id}/escalate": {"post"},
    "/api/v1/risk-rules/{public_id}/evaluate": {"post"},
    "/api/v1/operating-issues": {"get", "post"},
    "/api/v1/operating-issues/{public_id}/decisions": {"post"},
    "/api/v1/operating-issues/{public_id}/iteration-proposal": {"post"},
    "/api/v1/retirement-plans": {"post"},
    "/api/v1/retirement-plans/{public_id}/validate": {"post"},
    "/api/v1/retirement-plans/{public_id}/submit": {"post"},
    "/api/v1/retirement-plans/{public_id}/execute": {"post"},
    "/api/v1/stage-gates/{public_id}/retirement-management-conclusion": {"post"},
    "/api/v1/stage-gates/{public_id}/retirement-final-decision": {"post"},
    "/api/v1/operating-data/exports": {"post"},
}


def _generate_schema() -> dict[str, Any]:
    return SchemaGenerator().get_schema(request=None, public=True)


def test_phase5_operations_paths_and_methods_are_declared() -> None:
    schema = _generate_schema()
    paths = schema["paths"]
    missing_paths = [path for path in REQUIRED_PATH_METHODS if path not in paths]
    assert missing_paths == [], f"Missing OpenAPI paths: {missing_paths}"

    missing_methods: list[str] = []
    for path, required_methods in REQUIRED_PATH_METHODS.items():
        declared = {method.lower() for method in paths[path]}
        absent = sorted(required_methods - declared)
        for method in absent:
            missing_methods.append(f"{method.upper()} {path}")
    assert missing_methods == [], f"Missing OpenAPI methods: {missing_methods}"
