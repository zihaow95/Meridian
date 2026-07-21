"""Code-registered JSON schemas for configuration definitions."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

FILE_UPLOAD_DEFINITION_CODE = "platform.file_upload"
PROJECT_EXECUTION_TEMPLATE_CODE = "PROJECT_EXECUTION_TEMPLATE"
OPERATING_SOURCE_MAPPING_CODE = "OPERATING_SOURCE_MAPPING"

_REQUIRED_CORE_STAGES = ["D1", "D2", "D3", "D4", "D5", "L1", "L2", "L3"]
_FORBIDDEN_SCRIPT_KEYS = frozenset(
    {
        "expression",
        "sql",
        "python",
        "python_code",
        "script",
        "api_key",
        "password",
        "secret",
        "token",
        "credentials",
        "credential",
    }
)

_SCHEMAS: dict[str, dict[str, Any]] = {
    FILE_UPLOAD_DEFINITION_CODE: {
        "type": "object",
        "additionalProperties": False,
        "required": ["allowed_mime_types", "max_bytes"],
        "properties": {
            "allowed_mime_types": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
            "max_bytes": {"type": "integer", "minimum": 1},
        },
    },
    PROJECT_EXECUTION_TEMPLATE_CODE: {
        "type": "object",
        "additionalProperties": False,
        "required": ["template_code", "project_type", "stages"],
        "properties": {
            "template_code": {"type": "string", "minLength": 1},
            "project_type": {"type": "string", "minLength": 1},
            "stages": {
                "type": "array",
                "minItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "name", "sequence_no", "depends_on"],
                    "properties": {
                        "code": {"type": "string", "minLength": 1},
                        "name": {"type": "string", "minLength": 1},
                        "sequence_no": {"type": "integer", "minimum": 1},
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "gate": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["gate_code", "gate_type"],
                            "properties": {
                                "gate_code": {"type": "string", "minLength": 1},
                                "gate_type": {"type": "string", "minLength": 1},
                            },
                        },
                    },
                },
            },
            "tasks": {"type": "array"},
            "deliverables": {"type": "array"},
            "gates": {"type": "array"},
        },
    },
    OPERATING_SOURCE_MAPPING_CODE: {
        "type": "object",
        "additionalProperties": False,
        "required": ["source_priority", "mapping_rules"],
        "properties": {
            "source_priority": {"type": "integer", "minimum": 1},
            "mapping_rules": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["external_field", "internal_field"],
                    "properties": {
                        "external_field": {"type": "string", "minLength": 1},
                        "internal_field": {"type": "string", "minLength": 1},
                    },
                },
            },
            "reasonable_ranges": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "min": {"type": "string"},
                        "max": {"type": "string"},
                    },
                },
            },
        },
    },
}


def get_schema(definition_code: str) -> dict[str, Any] | None:
    return _SCHEMAS.get(definition_code)


def validate_content(definition_code: str, content: dict[str, Any]) -> list[str]:
    schema = get_schema(definition_code)
    if schema is None:
        return [f"No schema registered for definition code: {definition_code}"]
    validator = Draft202012Validator(schema)
    errors = [
        error.message for error in sorted(validator.iter_errors(content), key=lambda e: e.path)
    ]
    if definition_code == PROJECT_EXECUTION_TEMPLATE_CODE:
        errors.extend(_validate_project_template_rules(content))
    if definition_code == OPERATING_SOURCE_MAPPING_CODE:
        errors.extend(_reject_forbidden_script_keys(content))
    return errors


def _validate_project_template_rules(content: dict[str, Any]) -> list[str]:
    stages = content.get("stages") or []
    codes = [stage.get("code") for stage in stages if isinstance(stage, dict)]
    errors: list[str] = []
    if len(codes) != len(set(codes)):
        errors.append("Stage codes must be unique.")
    missing = [code for code in _REQUIRED_CORE_STAGES if code not in codes]
    if missing:
        errors.append(f"Template must include required stages: {', '.join(missing)}")
    code_set = set(codes)
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        for dep in stage.get("depends_on") or []:
            if dep not in code_set:
                errors.append(f"Unknown stage dependency: {dep}")
        if stage.get("code") == "L2":
            gate = stage.get("gate") or {}
            if gate.get("gate_code") != "FIRST_LAUNCH":
                errors.append("L2 must use FIRST_LAUNCH major gate.")
    return errors


def _reject_forbidden_script_keys(content: dict[str, Any], *, path: str = "") -> list[str]:
    errors: list[str] = []
    if not isinstance(content, dict):
        return errors
    for key, value in content.items():
        full = f"{path}.{key}" if path else key
        if key.lower() in _FORBIDDEN_SCRIPT_KEYS:
            errors.append(f"Forbidden configuration key: {full}")
        if isinstance(value, dict):
            errors.extend(_reject_forbidden_script_keys(value, path=full))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    errors.extend(_reject_forbidden_script_keys(item, path=f"{full}[{index}]"))
    return errors
