import threading
import json
from typing import Any

class SchemaRegistry:
    def __init__(self) -> None:
        self._schemas: dict[str, dict] = {}
        self._lock    = threading.Lock()

    def register(self, name: str, schema: dict, version: str = "1.0") -> None:
        with self._lock:
            self._schemas[name] = {"schema": schema, "version": version}

    def validate(self, name: str, data: dict) -> tuple[bool, str]:
        with self._lock:
            entry = self._schemas.get(name)
        if entry is None:
            return True, "schema not registered (passthrough)"
        schema = entry["schema"]
        try:
            import jsonschema
            jsonschema.validate(data, schema)
            return True, "ok"
        except ImportError:
            required = schema.get("required", [])
            missing  = [k for k in required if k not in data]
            if missing:
                return False, f"missing required keys: {missing}"
            return True, "ok (shallow)"
        except Exception as _e:
            return False, str(_e)[:200]

    def get(self, name: str) -> dict | None:
        with self._lock:
            entry = self._schemas.get(name)
            return entry["schema"] if entry else None

    def names(self) -> list[str]:
        with self._lock:
            return list(self._schemas.keys())

    def _register_builtin_schemas(self) -> None:
        self.register("plan_output", {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["step", "action", "tool"],
                "properties": {
                    "step":   {"type": "integer"},
                    "action": {"type": "string"},
                    "tool":   {"type": "string"},
                    "args":   {"type": "object"},
                    "depends_on": {"type": "array", "items": {"type": "integer"}},
                }
            }
        }, version="1.0")

        self.register("consolidation_output", {
            "type": "object",
            "properties": {
                "facts":   {"type": "array", "items": {"type": "string"}},
                "profile": {"type": "object"},
                "triples": {"type": "array"},
                "retain":  {"type": "array", "items": {"type": "string"}},
            }
        }, version="1.0")

        self.register("critic_output", {
            "type": "object",
            "required": ["passed"],
            "properties": {
                "passed":   {"type": "boolean"},
                "category": {"type": "string"},
                "evidence": {"type": "string"},
                "fix_hint": {"type": "string"},
            }
        }, version="1.0")

        self.register("semantic_fact", {
            "type": "object",
            "required": ["entity", "relation", "attribute", "value"],
            "properties": {
                "entity":     {"type": "string"},
                "relation":   {"type": "string"},
                "attribute":  {"type": "string"},
                "value":      {"type": "string"},
                "confidence": {"type": "number"},
                "source":     {"type": "string"},
            }
        }, version="1.0")

SCHEMA_REGISTRY = SchemaRegistry()
SCHEMA_REGISTRY._register_builtin_schemas()
