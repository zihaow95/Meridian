"""Code-registered JSON schemas for configuration definitions."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

FILE_UPLOAD_DEFINITION_CODE = "platform.file_upload"

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
}


def get_schema(definition_code: str) -> dict[str, Any] | None:
    return _SCHEMAS.get(definition_code)


def validate_content(definition_code: str, content: dict[str, Any]) -> list[str]:
    schema = get_schema(definition_code)
    if schema is None:
        return [f"No schema registered for definition code: {definition_code}"]
    validator = Draft202012Validator(schema)
    return [error.message for error in sorted(validator.iter_errors(content), key=lambda e: e.path)]
