"""Code-registered JSON schemas for configuration definitions."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

FILE_UPLOAD_DEFINITION_CODE = "platform.file_upload"
PROJECT_EXECUTION_TEMPLATE_CODE = "PROJECT_EXECUTION_TEMPLATE"
OPERATING_SOURCE_MAPPING_CODE = "OPERATING_SOURCE_MAPPING"
TECHNICAL_FILE_CATALOG_CODE = "TECHNICAL_FILE_CATALOG"
PRODUCT_MATERIAL_REQUIREMENTS_CODE = "PRODUCT_MATERIAL_REQUIREMENTS"
NOTIFICATION_TEMPLATE_CATALOG_CODE = "NOTIFICATION_TEMPLATE_CATALOG"
NOTIFICATION_DELIVERY_POLICY_CODE = "NOTIFICATION_DELIVERY_POLICY"

# Mirrors authorization.models.role.DataSensitivityLevel. Kept as literals because
# migrations import this module before the app registry is ready; a test asserts
# the two stay in sync.
SENSITIVITY_LEVELS = [
    "PUBLIC_SUMMARY",
    "INTERNAL",
    "PROJECT_CONTROLLED",
    "SENSITIVE_CONTROLLED",
    "HIGHLY_SENSITIVE",
]
MATERIAL_REQUIREMENT_STATES = ["REQUIRED", "OPTIONAL", "NOT_APPLICABLE"]
NOTIFICATION_CATEGORIES = [
    "ACTION_REQUIRED",
    "DEADLINE",
    "BUSINESS_ALERT",
    "PROCESS_RESULT",
    "SYSTEM_FAILURE",
    "INFORMATION",
]
NOTIFICATION_LEVELS = ["URGENT", "IMPORTANT", "NORMAL"]
# DingTalk delivery is deferred past phase 6, so the policy schema cannot express it.
NOTIFICATION_CHANNELS = ["IN_APP"]

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
    TECHNICAL_FILE_CATALOG_CODE: {
        "type": "object",
        "additionalProperties": False,
        "required": ["catalog_items"],
        "properties": {
            "catalog_items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "item_code",
                        "name",
                        "allowed_mime_types",
                        "max_bytes",
                        "preview_enabled",
                        "default_sensitivity_level",
                        "retention_years",
                    ],
                    "properties": {
                        "item_code": {"type": "string", "minLength": 1},
                        "name": {"type": "string", "minLength": 1},
                        "allowed_mime_types": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                            "minItems": 1,
                        },
                        "max_bytes": {"type": "integer", "minimum": 1},
                        "preview_enabled": {"type": "boolean"},
                        "default_sensitivity_level": {"enum": SENSITIVITY_LEVELS},
                        "retention_years": {"type": "integer", "minimum": 1},
                        # Absent means usable; retiring an item must be explicit.
                        "enabled": {"type": "boolean"},
                    },
                },
            }
        },
    },
    PRODUCT_MATERIAL_REQUIREMENTS_CODE: {
        "type": "object",
        "additionalProperties": False,
        "required": ["requirements"],
        "properties": {
            "requirements": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["product_category_code", "lifecycle_state", "materials"],
                    "properties": {
                        "product_category_code": {"type": "string", "minLength": 1},
                        "lifecycle_state": {"type": "string", "minLength": 1},
                        "materials": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["material_type_code", "requirement"],
                                "properties": {
                                    "material_type_code": {"type": "string", "minLength": 1},
                                    "requirement": {"enum": MATERIAL_REQUIREMENT_STATES},
                                },
                            },
                        },
                    },
                },
            }
        },
    },
    NOTIFICATION_TEMPLATE_CATALOG_CODE: {
        "type": "object",
        "additionalProperties": False,
        "required": ["templates"],
        "properties": {
            "templates": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "template_code",
                        "category",
                        "default_level",
                        "summary_template",
                        "allowed_variables",
                    ],
                    "properties": {
                        "template_code": {"type": "string", "minLength": 1},
                        "category": {"enum": NOTIFICATION_CATEGORIES},
                        "default_level": {"enum": NOTIFICATION_LEVELS},
                        "summary_template": {"type": "string", "minLength": 1},
                        "allowed_variables": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                },
            }
        },
    },
    NOTIFICATION_DELIVERY_POLICY_CODE: {
        "type": "object",
        "additionalProperties": False,
        "required": ["rules"],
        "properties": {
            "rules": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["category", "level", "channels"],
                    "properties": {
                        "category": {"enum": NOTIFICATION_CATEGORIES},
                        "level": {"enum": NOTIFICATION_LEVELS},
                        "channels": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"enum": NOTIFICATION_CHANNELS},
                        },
                    },
                },
            }
        },
    },
}

# Definitions whose content is business data rather than executable logic.
_SCRIPT_GUARDED_CODES = frozenset(
    {
        OPERATING_SOURCE_MAPPING_CODE,
        TECHNICAL_FILE_CATALOG_CODE,
        PRODUCT_MATERIAL_REQUIREMENTS_CODE,
        NOTIFICATION_TEMPLATE_CATALOG_CODE,
        NOTIFICATION_DELIVERY_POLICY_CODE,
    }
)


def get_schema(definition_code: str) -> dict[str, Any] | None:
    if definition_code in _SCHEMAS:
        return _SCHEMAS[definition_code]
    if definition_code.startswith(f"{OPERATING_SOURCE_MAPPING_CODE}."):
        return _SCHEMAS[OPERATING_SOURCE_MAPPING_CODE]
    return None


def validate_content(definition_code: str, content: dict[str, Any]) -> list[str]:
    schema = get_schema(definition_code)
    if schema is None:
        return [f"No schema registered for definition code: {definition_code}"]
    validator = Draft202012Validator(schema)
    errors = [
        error.message for error in sorted(validator.iter_errors(content), key=lambda e: e.path)
    ]
    schema_code = (
        OPERATING_SOURCE_MAPPING_CODE
        if definition_code.startswith(f"{OPERATING_SOURCE_MAPPING_CODE}.")
        else definition_code
    )
    if schema_code == PROJECT_EXECUTION_TEMPLATE_CODE:
        errors.extend(_validate_project_template_rules(content))
    if schema_code == TECHNICAL_FILE_CATALOG_CODE:
        errors.extend(_validate_technical_file_catalog(content))
    if schema_code == PRODUCT_MATERIAL_REQUIREMENTS_CODE:
        errors.extend(_validate_product_material_requirements(content))
    if schema_code == NOTIFICATION_TEMPLATE_CATALOG_CODE:
        errors.extend(_validate_notification_template_catalog(content))
    if schema_code == NOTIFICATION_DELIVERY_POLICY_CODE:
        errors.extend(_validate_notification_delivery_policy(content))
    if schema_code in _SCRIPT_GUARDED_CODES:
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


def _validate_technical_file_catalog(content: dict[str, Any]) -> list[str]:
    codes = [
        item.get("item_code")
        for item in content.get("catalog_items") or []
        if isinstance(item, dict)
    ]
    return _duplicate_key_errors(codes, label="item_code")


def _validate_product_material_requirements(content: dict[str, Any]) -> list[str]:
    keys = [
        (row.get("product_category_code"), row.get("lifecycle_state"))
        for row in content.get("requirements") or []
        if isinstance(row, dict)
    ]
    errors = _duplicate_key_errors(keys, label="product_category_code/lifecycle_state")
    for index, row in enumerate(content.get("requirements") or []):
        if not isinstance(row, dict):
            continue
        material_codes = [
            item.get("material_type_code")
            for item in row.get("materials") or []
            if isinstance(item, dict)
        ]
        nested = _duplicate_key_errors(material_codes, label="material_type_code")
        errors.extend(f"requirements[{index}]: {message}" for message in nested)
    return errors


def _validate_notification_template_catalog(content: dict[str, Any]) -> list[str]:
    codes = [
        item.get("template_code")
        for item in content.get("templates") or []
        if isinstance(item, dict)
    ]
    return _duplicate_key_errors(codes, label="template_code")


def _validate_notification_delivery_policy(content: dict[str, Any]) -> list[str]:
    pairs = [
        (rule.get("category"), rule.get("level"))
        for rule in content.get("rules") or []
        if isinstance(rule, dict)
    ]
    errors = _duplicate_key_errors(pairs, label="category/level")
    present = {(category, level) for category, level in pairs if category and level}
    required = {
        (category, level) for category in NOTIFICATION_CATEGORIES for level in NOTIFICATION_LEVELS
    }
    missing = sorted(required - present)
    if missing:
        rendered = ", ".join(f"{category}/{level}" for category, level in missing)
        errors.append(
            "Delivery policy must cover every category and level pair; missing: " + rendered
        )
    return errors


def _duplicate_key_errors(values: list[Any], *, label: str) -> list[str]:
    seen: set[Any] = set()
    duplicates: set[Any] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        else:
            seen.add(value)
    if not duplicates:
        return []
    rendered = ", ".join(sorted(str(item) for item in duplicates))
    return [f"Duplicate {label} values are not allowed: {rendered}"]
