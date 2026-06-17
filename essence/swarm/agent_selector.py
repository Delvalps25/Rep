from __future__ import annotations
import enum as _enum
import dataclasses as _dc
from typing import Any, List as list
from essence.swarm.specialist import AgentRole, AgentCapabilities, AgentRegistry

class AgentSelector:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry
    def select_best_role(self, task_description: str,
                         required_skills: list[str] | None = None) -> AgentRole:
        t = task_description.lower()
        if any(k in t for k in ("search", "find", "research", "lookup")):
            return AgentRole.RESEARCHER
        if any(k in t for k in ("code", "python", "script", "refactor")):
            return AgentRole.CODER
        if any(k in t for k in ("analyze", "data", "csv", "plot", "chart")):
            return AgentRole.DATA_ANALYST
        if any(k in t for k in ("plan", "breakdown", "steps")):
            return AgentRole.PLANNER
        return AgentRole.EXECUTOR
