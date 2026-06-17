from __future__ import annotations
import os
import time
import json
from pathlib import Path
from typing import Any, List, Dict, Optional
from pydantic import BaseModel, ConfigDict, model_validator
from essence.core.events import log
from essence.swarm.workflow_engine import WorkflowEngine
from essence.swarm.dag_executor import DAGWorkflowExecutor
from essence.memory.memory import Memory
from essence.safety.policy import CapabilityPolicy
from essence.swarm.failure_handler import DecisionQueue
from essence.quality.verifier import VerifierLayer
from essence.proactive.engine import ProactiveEngine

class AgentConfig(BaseModel):
    """Pydantic v2 agent configuration — validated on construction."""
    model_config = ConfigDict(frozen=False, arbitrary_types_allowed=True)

    provider:       Any
    model:          str
    workspace:      Path
    thinking:       bool  = False
    budget:         int   = 1024
    max_steps:      int   = 12
    critic:         bool  = True
    memory_window:  int   = 10
    use_tools:      bool  = True
    allow_outside:  bool  = False
    autonomy_level: int   = 1
    session_id:     str   = ""
    team_id:        str   = "local"
    cost_budget:    int   = 0
    sop_dir:        Optional[str] = None

    @model_validator(mode='after')
    def _validate_ranges(self) -> 'AgentConfig':
        if self.autonomy_level not in (0, 1, 2):
            raise ValueError(f'autonomy_level must be 0, 1, or 2; got {self.autonomy_level}')
        return self

class Agent:
    """
    Production-grade agent session.
    """
    def __init__(self, cfg: AgentConfig,
                 soul: str = "",
                 identity: str = "",
                 tools_md: str = "",
                 skills: Dict[str, str] | None = None,
                 memory: Memory | None = None,
                 hw: Any = None):
        self.cfg         = cfg
        self.soul        = soul
        self.identity    = identity
        self.tools_md    = tools_md
        self.skills      = skills or {}
        self.memory      = memory or Memory(cfg.workspace)
        self.history: List[Dict] = []
        self._session_id = f"s{int(time.time())}_{id(self) & 0xFFFF:04x}"
        self._hw         = hw
        self._workflow_engine = WorkflowEngine(cfg.workspace)
        self._cap_policy      = CapabilityPolicy(autonomy_level=cfg.autonomy_level)
        self._decision_queue  = DecisionQueue(cfg.workspace)
        self._verifier        = VerifierLayer(cfg.provider, cfg.model)
        self._proactive       = ProactiveEngine(cfg.workspace, self.memory)

    async def chat(self, message: str) -> str:
        """Simple chat interface."""
        self.history.append({"role": "user", "content": message})
        # Mocked response
        response = f"I am UAIS. You said: {message}"
        self.history.append({"role": "assistant", "content": response})
        return response
