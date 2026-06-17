from __future__ import annotations
import re
import sys
import time
import dataclasses as _dc
from pathlib import Path
from typing import Any, List as list
from essence.intent.task_classifier import RequestComplexity, _classify_complexity

@_dc.dataclass
class NormalizedInput:
    text:     str
    files:    list[str] = _dc.field(default_factory=list)
    images:   list[str] = _dc.field(default_factory=list)
    metadata: dict      = _dc.field(default_factory=dict)
    event_id: str       = ""

class InputNormalizer:
    def normalize(self, raw: Any) -> NormalizedInput:
        if isinstance(raw, str):
            return NormalizedInput(text=raw)
        if isinstance(raw, dict):
            return NormalizedInput(
                text=raw.get("text", ""),
                files=raw.get("files", []),
                images=raw.get("images", []),
                metadata=raw.get("metadata", {}),
                event_id=raw.get("event_id", "")
            )
        return NormalizedInput(text=str(raw))

class LanguageUnderstanding:
    def __init__(self, provider: Any = None, model: str = ""):
        self.provider = provider
        self.model = model

    def extract_entities(self, text: str) -> list[dict]:
        entities = []
        for m in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", text):
            entities.append({"text": m.group(0), "type": "DATE"})
        for m in re.finditer(r"[\w.]+@[\w.]+", text):
            entities.append({"text": m.group(0), "type": "EMAIL"})
        return entities

    def resolve_coreferences(self, text: str, context: str = "") -> str:
        return text

class ContextInjector:
    def __init__(self, workspace: Path | None = None):
        self.workspace = workspace

    def inject(self, task_spec: TaskSpec, session_id: str = "", user_id: str = "") -> TaskSpec:
        if not task_spec.session_id:
            task_spec.session_id = session_id
        task_spec.context["platform"] = sys.platform
        task_spec.context["python_version"] = sys.version.split()[0]
        task_spec.context["timestamp"] = time.time()
        if user_id:
            task_spec.user_id = user_id
            task_spec.context["user_profile"] = {"id": user_id, "role": "admin"}
        return task_spec

@_dc.dataclass
class TaskConstraint:
    kind:  str
    value: str
    hard:  bool = True

@_dc.dataclass
class TaskSpec:
    goal:        str
    subtasks:    list[dict]           = _dc.field(default_factory=list)
    constraints: list[TaskConstraint] = _dc.field(default_factory=list)
    priority:    str                  = "medium"
    complexity:  RequestComplexity  = RequestComplexity.MODERATE
    context:     dict                 = _dc.field(default_factory=dict)
    user_id:     str                  = ""
    session_id:  str                  = ""
    analytical_mode: str | None = None
    prism_config: dict = _dc.field(default_factory=dict)

_CONSTRAINT_PATTERNS: list[tuple[str, str]] = [
    (r"within\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|seconds?|secs?|days?)", "time"),
    (r"budget\s*(?:of|:)?\s*\$?(\d+)", "budget"),
    (r"(?:output|return|format)\s+(?:as|in)\s+(json|csv|markdown|html|pdf)", "format"),
    (r"(?:no|avoid|don.?t|without)\s+(network|internet|api|cloud)", "scope"),
    (r"(?:low|minimal|zero)\s+risk", "risk"),
    (r"(?:use|only|prefer)\s+(shell|python|web_search|read_file)", "tool"),
]

def extract_constraints(text: str) -> list[TaskConstraint]:
    constraints: list[TaskConstraint] = []
    for pattern, kind in _CONSTRAINT_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            constraints.append(TaskConstraint(kind=kind, value=m.group(0).strip()))
    return constraints

def _classify_priority(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("urgent", "asap", "immediately", "critical")): return "critical"
    if any(k in t for k in ("important", "high priority", "soon")): return "high"
    if any(k in t for k in ("when you can", "low priority", "no rush")): return "low"
    return "medium"

def build_task_spec(user_input: Any, session_id: str = "",
                    user_id: str = "", context: dict | None = None,
                    provider: Any = None, model: str = "") -> TaskSpec:
    normalizer = InputNormalizer()
    norm = normalizer.normalize(user_input)
    nlu = LanguageUnderstanding(provider, model)
    text = nlu.resolve_coreferences(norm.text)
    entities = nlu.extract_entities(text)
    spec = TaskSpec(
        goal=text.strip(),
        constraints=extract_constraints(text),
        priority=_classify_priority(text),
        complexity=_classify_complexity(text),
        context=context or {},
        user_id=user_id,
        session_id=session_id
    )
    spec.context["entities"] = entities
    spec.context["metadata"] = norm.metadata
    if norm.files: spec.context["files"] = norm.files
    if norm.images: spec.context["images"] = norm.images
    injector = ContextInjector()
    spec = injector.inject(spec, session_id=session_id, user_id=user_id)
    t = text.lower()
    if any(k in t for k in ("analyze", "explore", "patterns", "summary")):
        spec.analytical_mode = "EXPLORE"
    elif any(k in t for k in ("correlate", "related", "relationship")):
        spec.analytical_mode = "CORRELATE"
    elif any(k in t for k in ("predict", "forecast", "future", "outcome")):
        spec.analytical_mode = "PREDICT"
    elif any(k in t for k in ("compare", "diff", "change")):
        spec.analytical_mode = "DELTA"
    if spec.analytical_mode:
        max_wave = 2
        if any(k in t for k in ("quick", "fast", "brief")): max_wave = 1
        elif any(k in t for k in ("deep", "thorough", "exhaustive")): max_wave = 3
        spec.prism_config = {
            "mode": "SINGLE",
            "max_wave": max_wave,
            "focus_categories": [spec.analytical_mode]
        }
    return spec
