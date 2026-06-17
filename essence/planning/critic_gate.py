from __future__ import annotations
import json
import re
from typing import Any, Callable, list
from essence.config import BaseModel, ConfigDict

FAILURE_CATEGORIES = [
    "PlanAdherenceFailure",
    "InventionOfInformation",
    "ToolMisuse",
    "GoalDrift",
    "ContextLoss",
    "InvalidState",
    "PrematureTermination",
    "PermissionViolation",
    "FormatError",
]

_CRITIC_GATE_SYS = (
    "You are a CriticGate validator. Given a step action and its result, "
    "evaluate whether the step completed correctly against the tool constraints. "
    "Respond ONLY with JSON (no markdown, no prose): "
    '{"pass": true/false, '
    '"category": "<one of: ' + '|'.join(FAILURE_CATEGORIES) + '> or null", '
    '"evidence": "<brief quote from result that shows the issue or null>", '
    '"fix_hint": "<concrete corrective action or null>"}'
)

class CriticResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    passed:   bool
    category: str | None = None
    evidence: str | None = None
    fix_hint: str | None = None

    @classmethod
    def ok(cls) -> 'CriticResult':
        return cls(passed=True, category=None, evidence=None, fix_hint=None)

    @classmethod
    def safe_block(cls, reason: str) -> 'CriticResult':
        return cls(
            passed=False,
            category='FormatError',
            evidence=f'LLM output could not be parsed as valid CriticResult: {reason}',
            fix_hint='Re-run the step with a clearer prompt.',
        )

    @classmethod
    def _try_parse(cls, raw: str) -> "CriticResult | None":
        clean = re.sub(r"```[a-zA-Z]*", "", raw).strip()
        m = re.search(r'\{(?:[^{}]|\{[^{}]*\})*"pass"(?:[^{}]|\{[^{}]*\})*\}', clean, re.S)
        if m: clean = m.group(0)
        try:
            d = json.loads(clean)
            passed = bool(d.get("pass", True))
            category = d.get("category")
            if category is not None and not isinstance(category, str): return None
            return cls(
                passed=passed,
                category=category if category in FAILURE_CATEGORIES else None,
                evidence=str(d['evidence']) if d.get('evidence') else None,
                fix_hint=str(d['fix_hint']) if d.get('fix_hint') else None,
            )
        except Exception: return None

    @classmethod
    def from_json(cls, raw: str,
                  repair_fn: Callable[[str, str], str] | None = None
                  ) -> "CriticResult":
        result = cls._try_parse(raw)
        if result is not None: return result
        if repair_fn is not None:
            schema = ('{"pass": true/false, "category": "' +
                      '|'.join(FAILURE_CATEGORIES) + ' or null", '
                      '"evidence": "string or null", "fix_hint": "string or null"}')
            try:
                repaired = repair_fn(raw, schema)
                result2  = cls._try_parse(repaired)
                if result2 is not None: return result2
            except Exception: pass
        return cls.safe_block(raw[:120])

def _synthesise_constraints(tools_md: str) -> list[str]:
    constraints = []
    for line in tools_md.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            constraints.append(line[2:].strip())
    return constraints
