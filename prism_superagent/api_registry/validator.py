"""Dependency-free response validation for small JSON Schema-like contracts."""

import json


class ResponseValidationError(ValueError):
    pass


class ResponseValidator:
    def validate(self, payload, response_type, schema=None):
        if response_type == "text":
            if not isinstance(payload, str):
                raise ResponseValidationError("Expected a text response.")
            return {"response_valid": True, "schema_valid": True}
        if response_type != "json":
            raise ResponseValidationError(f"Unsupported response type: {response_type}")
        try:
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ResponseValidationError(
                "The response is not valid JSON data."
            ) from None
        _validate_schema(payload, schema or {}, "$")
        return {"response_valid": True, "schema_valid": True}


def _validate_schema(value, schema, path):
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in types):
            raise ResponseValidationError(f"{path} must have JSON type {expected}.")
    if isinstance(value, dict):
        missing = [key for key in schema.get("required", []) if key not in value]
        if missing:
            raise ResponseValidationError(
                f"{path} is missing required keys: {', '.join(missing)}."
            )
        for key, child_schema in schema.get("properties", {}).items():
            if key in value:
                _validate_schema(value[key], child_schema, f"{path}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema(item, schema["items"], f"{path}[{index}]")


def _matches_type(value, expected):
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False
