"""Domain errors for work item commands."""

from __future__ import annotations

from apps.platform.api.errors import ApiError


class TaskVersionConflict(ApiError):
    code = "TASK_VERSION_CONFLICT"
    message = "The task was updated by another operation."
    status_code = 409


class CoreTaskCannotCancel(ApiError):
    code = "CORE_TASK_CANNOT_CANCEL"
    message = "Core tasks cannot be cancelled directly."
    status_code = 409


class HardDependencyBlocksStart(ApiError):
    code = "HARD_DEPENDENCY_BLOCKS_START"
    message = "A hard predecessor is not complete."
    status_code = 409


class TaskDependencyCycle(ApiError):
    code = "TASK_DEPENDENCY_CYCLE"
    message = "Task dependencies must form a DAG."
    status_code = 409


class TaskNotFound(ApiError):
    code = "RESOURCE_NOT_FOUND"
    message = "The requested resource was not found."
    status_code = 404
