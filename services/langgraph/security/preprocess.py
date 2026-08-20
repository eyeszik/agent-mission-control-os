from typing import Any

from services.langgraph.security.sanitize import sanitize_input


def sanitize_deep(value: Any) -> Any:
    """Apply the existing string sanitizer recursively to JSON-like containers."""

    if isinstance(value, str):
        return sanitize_input({"value": value})["value"]
    if isinstance(value, dict):
        return {key: sanitize_deep(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_deep(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_deep(item) for item in value)
    return value
