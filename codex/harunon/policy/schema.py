"""Dependency-free JSON Schema subset used by the distributed kernel."""

from __future__ import annotations

import re
from typing import Any


def validate(instance: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None and not _matches_type(instance, expected_type):
        return [f"{path}: expected type {expected_type!r}"]
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: must be one of {schema['enum']!r}")
    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: string is shorter than minLength")
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path}: does not match pattern {schema['pattern']!r}")
    if isinstance(instance, int) and not isinstance(instance, bool):
        if instance < schema.get("minimum", instance):
            errors.append(f"{path}: value is below minimum")
    if isinstance(instance, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}: missing required property '{key}'")
        for key, value in instance.items():
            child_schema = properties.get(key)
            if child_schema is None:
                if schema.get("additionalProperties") is False:
                    errors.append(f"{path}: additional property '{key}' is not allowed")
                continue
            errors.extend(validate(value, child_schema, f"{path}.{key}"))
    if isinstance(instance, list) and "items" in schema:
        for index, value in enumerate(instance):
            errors.extend(validate(value, schema["items"], f"{path}[{index}]"))
    return errors


def _matches_type(instance: Any, expected: str | list[str]) -> bool:
    choices = expected if isinstance(expected, list) else [expected]
    mapping: dict[str, type[Any]] = {
        "array": list,
        "boolean": bool,
        "integer": int,
        "object": dict,
        "string": str,
    }
    for choice in choices:
        kind = mapping.get(choice)
        if kind is None:
            continue
        if isinstance(instance, kind) and not (
            choice == "integer" and isinstance(instance, bool)
        ):
            return True
    return False
