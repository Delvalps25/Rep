import os
import json
import time
import threading
import dataclasses as _dc
from pathlib import Path
from typing import Dict, Optional

@_dc.dataclass
class TaskCost:
    """Accumulated cost record for a single task run."""
    task_id:      str
    model:        str
    prompt_tok:   int   = 0
    completion_tok: int = 0
    tool_calls:   int   = 0
    started_at:   float = _dc.field(default_factory=time.time)
    finished_at:  float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tok + self.completion_tok

    def to_dict(self) -> dict:
        return {
            "task_id":        self.task_id,
            "model":          self.model,
            "prompt_tok":     self.prompt_tok,
            "completion_tok": self.completion_tok,
            "tool_calls":     self.tool_calls,
            "total_tokens":   self.total_tokens,
            "started_at":     self.started_at,
            "finished_at":    self.finished_at,
            "duration_s":     round(self.finished_at - self.started_at, 2)
                              if self.finished_at else None,
        }

class CostTracker:
    """
    Thread-safe token cost accumulator with optional budget enforcement.
    """

    def __init__(self, workspace: Path,
                 budget: int = 0,
                 log_enabled: Optional[bool] = None) -> None:
        self._ws          = workspace
        self._budget      = budget or int(os.environ.get("UAIS_COST_BUDGET", "0"))
        self._log_path    = workspace / "cost_log.jsonl"
        self._log_enabled = (
            log_enabled if log_enabled is not None
            else os.environ.get("UAIS_COST_LOG", "1") == "1"
        )
        self._current:  Dict[str, TaskCost] = {}
        self._lock      = threading.Lock()
        self._totals: Dict[str, int] = {}   # task_id → running total

    def start_task(self, task_id: str, model: str = "") -> TaskCost:
        with self._lock:
            cost = TaskCost(task_id=task_id, model=model)
            self._current[task_id] = cost
            self._totals[task_id]  = 0
            return cost

    def record(self, task_id: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        with self._lock:
            if task_id in self._current:
                cost = self._current[task_id]
                cost.prompt_tok += prompt_tokens
                cost.completion_tok += completion_tokens
                self._totals[task_id] += (prompt_tokens + completion_tokens)

                if self._budget > 0 and self._totals[task_id] > self._budget:
                    log.warning("budget_exceeded", extra={"task_id": task_id, "total": self._totals[task_id], "budget": self._budget})

    def finish_task(self, task_id: str) -> Optional[TaskCost]:
        with self._lock:
            if task_id in self._current:
                cost = self._current.pop(task_id)
                cost.finished_at = time.time()
                self._totals.pop(task_id, None)

                if self._log_enabled:
                    with open(self._log_path, "a") as f:
                        f.write(json.dumps(cost.to_dict()) + "\n")
                return cost
        return None
