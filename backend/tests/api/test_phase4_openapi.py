"""Phase 4 OpenAPI path contract for execution APIs."""

from __future__ import annotations

from typing import Any

from drf_spectacular.generators import SchemaGenerator

REQUIRED_PATHS = (
    "/api/v1/projects",
    "/api/v1/projects/{public_id}",
    "/api/v1/projects/{public_id}/stages",
    "/api/v1/projects/{public_id}/members",
    "/api/v1/projects/{public_id}/tasks",
    "/api/v1/tasks/{public_id}",
    "/api/v1/tasks/{public_id}/assign",
    "/api/v1/projects/{public_id}/deliverables",
    "/api/v1/deliverables/{public_id}/revisions",
    "/api/v1/deliverable-revisions/{public_id}/submit",
    "/api/v1/professional-confirmations/{public_id}/decide",
    "/api/v1/stage-gates/{public_id}/validate",
    "/api/v1/stage-gates/{public_id}/submissions",
    "/api/v1/stage-gates/{public_id}/decision",
    "/api/v1/stage-gates/{public_id}/first-launch-decision",
    "/api/v1/projects/{public_id}/plan-changes",
    "/api/v1/plan-changes/{public_id}/confirm",
    "/api/v1/projects/{public_id}/emergency-executions",
    "/api/v1/project-stages/{public_id}/handling-requests",
    "/api/v1/execution-exceptions/{public_id}/confirm",
    "/api/v1/project-migration-batches",
)


def _generate_schema() -> dict[str, Any]:
    return SchemaGenerator().get_schema(request=None, public=True)


def test_phase4_execution_paths_are_declared() -> None:
    schema = _generate_schema()
    paths = schema["paths"]
    missing = [path for path in REQUIRED_PATHS if path not in paths]
    assert missing == [], f"Missing OpenAPI paths: {missing}"
