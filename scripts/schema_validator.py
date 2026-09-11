"""Lightweight JSON Schema validator (draft 2020-12 subset).

Supported keywords:
  type, required, properties, additionalProperties, items,
  enum, const, pattern, oneOf, $ref/$defs, minItems, maxItems

Returns a list of error strings (empty list = valid).
Error messages include a JSON path prefix, e.g. "$.foo.bar: …".
"""
from __future__ import annotations

import re
from typing import Any


def validate(data: Any, schema: dict[str, Any]) -> list[str]:
    """Validate *data* against *schema*.  Returns error strings."""
    resolver = _Resolver(schema)
    return resolver.validate(data, schema, "$")


class _Resolver:
    def __init__(self, root_schema: dict[str, Any]) -> None:
        self._defs: dict[str, Any] = root_schema.get("$defs", {})

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def validate(self, data: Any, schema: dict[str, Any], path: str) -> list[str]:
        # Resolve $ref first
        if "$ref" in schema:
            schema = self._resolve_ref(schema["$ref"])

        errors: list[str] = []

        # type
        if "type" in schema:
            errors.extend(self._check_type(data, schema["type"], path))
            if errors:
                # No point checking further if the type is wrong
                return errors

        # const
        if "const" in schema:
            if data != schema["const"]:
                errors.append(f"{path}: expected {schema['const']!r}, got {data!r}")

        # enum
        if "enum" in schema:
            if data not in schema["enum"]:
                errors.append(
                    f"{path}: must be one of {schema['enum']!r}, got {data!r}"
                )

        # pattern (strings only)
        if "pattern" in schema and isinstance(data, str):
            if not re.search(schema["pattern"], data):
                errors.append(
                    f"{path}: does not match pattern {schema['pattern']!r}"
                )

        # object keywords
        if isinstance(data, dict):
            errors.extend(self._check_object(data, schema, path))

        # array keywords
        if isinstance(data, list):
            errors.extend(self._check_array(data, schema, path))

        # allOf
        if "allOf" in schema:
            for sub in schema["allOf"]:
                errors.extend(self.validate(data, sub, path))

        # oneOf
        if "oneOf" in schema:
            errors.extend(self._check_one_of(data, schema["oneOf"], path))

        return errors

    # ------------------------------------------------------------------
    # Type checking
    # ------------------------------------------------------------------

    _TYPE_MAP: dict[str, type | tuple[type, ...]] = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "integer": int,
        "number": (int, float),
    }

    def _check_type(self, data: Any, type_spec: str | list, path: str) -> list[str]:
        types = type_spec if isinstance(type_spec, list) else [type_spec]
        for t in types:
            expected = self._TYPE_MAP.get(t)
            if expected is None:
                continue
            # bool is a subclass of int in Python; reject for integer/number
            if t in ("integer", "number") and isinstance(data, bool):
                continue
            if isinstance(data, expected):
                return []
        return [f"{path}: expected type {type_spec!r}, got {type(data).__name__}"]

    # ------------------------------------------------------------------
    # Object validation
    # ------------------------------------------------------------------

    def _check_object(
        self, data: dict, schema: dict[str, Any], path: str
    ) -> list[str]:
        errors: list[str] = []

        # required
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}: missing required property '{key}'")

        # properties
        props_schema = schema.get("properties", {})
        for key, sub_schema in props_schema.items():
            if key in data:
                child_path = f"{path}.{key}"
                errors.extend(self.validate(data[key], sub_schema, child_path))

        # additionalProperties
        if "additionalProperties" in schema:
            ap = schema["additionalProperties"]
            known_keys = set(props_schema.keys())
            extra_keys = set(data.keys()) - known_keys
            if ap is False:
                for key in sorted(extra_keys):
                    errors.append(f"{path}: additional property '{key}' is not allowed")
            elif isinstance(ap, dict):
                for key in sorted(extra_keys):
                    errors.extend(
                        self.validate(data[key], ap, f"{path}.{key}")
                    )

        return errors

    # ------------------------------------------------------------------
    # Array validation
    # ------------------------------------------------------------------

    def _check_array(
        self, data: list, schema: dict[str, Any], path: str
    ) -> list[str]:
        errors: list[str] = []

        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None and len(data) < min_items:
            errors.append(f"{path}: array length {len(data)} < minItems {min_items}")
        if max_items is not None and len(data) > max_items:
            errors.append(f"{path}: array length {len(data)} > maxItems {max_items}")

        if "items" in schema:
            for i, item in enumerate(data):
                errors.extend(self.validate(item, schema["items"], f"{path}[{i}]"))

        return errors

    # ------------------------------------------------------------------
    # oneOf
    # ------------------------------------------------------------------

    def _check_one_of(
        self, data: Any, sub_schemas: list[dict], path: str
    ) -> list[str]:
        matching = sum(
            1 for s in sub_schemas if not self.validate(data, s, path)
        )
        if matching == 1:
            return []
        if matching == 0:
            # Collect errors from each branch for a useful message
            branch_msgs: list[str] = []
            for i, s in enumerate(sub_schemas):
                errs = self.validate(data, s, path)
                if errs:
                    branch_msgs.append(f"  branch[{i}]: {errs[0]}")
            return [f"{path}: must match exactly one of the schemas\n" + "\n".join(branch_msgs)]
        return [f"{path}: matches {matching} schemas in oneOf (expected exactly 1)"]

    # ------------------------------------------------------------------
    # $ref resolution (local $defs only)
    # ------------------------------------------------------------------

    def _resolve_ref(self, ref: str) -> dict[str, Any]:
        if ref.startswith("#/$defs/"):
            name = ref[len("#/$defs/"):]
            if name in self._defs:
                return self._defs[name]
        raise ValueError(f"Cannot resolve $ref: {ref!r} (only local #/$defs/ supported)")
