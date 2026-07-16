"""Phase 4 OpenAPI path contract for execution APIs."""

from __future__ import annotations

from typing import Any

from drf_spectacular.generators import SchemaGenerator

REQUIRED_PATH_METHODS: dict[str, set[str]] = {
    "/api/v1/projects": {"get"},
    "/api/v1/projects/{public_id}": {"get"},
    "/api/v1/projects/{public_id}/stages": {"get"},
    "/api/v1/projects/{public_id}/members": {"post"},
    "/api/v1/projects/{public_id}/tasks": {"get", "post"},
    "/api/v1/tasks/{public_id}": {"patch"},
    "/api/v1/tasks/{public_id}/assign": {"post"},
    "/api/v1/tasks/{public_id}/transition": {"post"},
    "/api/v1/projects/{public_id}/deliverables": {"get", "post"},
    "/api/v1/deliverables/{public_id}/revisions": {"post"},
    "/api/v1/deliverable-revisions/{public_id}/submit": {"post"},
    "/api/v1/professional-confirmations/{public_id}/decide": {"post"},
    "/api/v1/stage-gates/{public_id}/validate": {"post"},
    "/api/v1/stage-gates/{public_id}/submissions": {"post"},
    "/api/v1/stage-gates/{public_id}/decision": {"post"},
    "/api/v1/stage-gates/{public_id}/first-launch-decision": {"post"},
    "/api/v1/stage-gates/{public_id}/first-launch-management-conclusion": {"post"},
    "/api/v1/stage-gates/{public_id}/first-launch-final-decision": {"post"},
    "/api/v1/projects/{public_id}/plan-changes": {"post"},
    "/api/v1/plan-changes/{public_id}/confirm": {"post"},
    "/api/v1/projects/{public_id}/emergency-executions": {"post"},
    "/api/v1/emergency-executions/{public_id}/complete": {"post"},
    "/api/v1/project-stages/{public_id}/handling-requests": {"post"},
    "/api/v1/execution-exceptions/{public_id}/confirm": {"post"},
    "/api/v1/project-migration-batches": {"post"},
}


def _generate_schema() -> dict[str, Any]:
    return SchemaGenerator().get_schema(request=None, public=True)


def test_phase4_execution_paths_and_methods_are_declared() -> None:
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
