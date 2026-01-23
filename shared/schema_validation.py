"""Simple JSON schema validation helpers using jsonschema (optional dependency)
"""

from typing import Any, Dict

try:
    import jsonschema
except Exception:
    jsonschema = None


def validate(instance: Dict[str, Any], schema: Dict[str, Any]) -> None:
    if jsonschema is None:
        raise RuntimeError("jsonschema library is not installed")
    jsonschema.validate(instance=instance, schema=schema)
