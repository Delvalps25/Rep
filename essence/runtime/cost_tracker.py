from __future__ import annotations
import os
import time
import json
import threading
import dataclasses as _dc
from pathlib import Path
from typing import Any
from essence.core.events import log
from essence.config import COST_BUDGET

class BudgetExceededError(RuntimeError):
    def __init__(self, spent: int, budget: int) -> None:
        super().__init__(
            f"Task budget exceeded: {spent:,} tokens used of {budget:,} limit. "
            f"Raise UAIS_COST_BUDGET or approve via DecisionQueue.")
        self.spent  = spent
        self.budget = budget

@_dc.dataclass
class TaskCost:
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
    def __init__(self, workspace: Path,
                 budget: int = 0,
                 log_enabled: bool | None = None) -> None:
        self._ws          = workspace
        self._budget      = budget or COST_BUDGET
        self._log_path    = workspace / "cost_log.jsonl"
        self._log_enabled = (
            log_enabled if log_enabled is not None
            else os.environ.get("UAIS_COST_LOG", "1") == "1"
        )
        self._current:  dict[str, TaskCost] = {}
        self._lock      = threading.Lock()
        self._totals: dict[str, int] = {}

    def start_task(self, task_id: str, model: str = "") -> TaskCost:
        with self._lock:
            tc = TaskCost(task_id=task_id, model=model)
            self._current[task_id] = tc
            self._totals[task_id]  = 0
            log.debug("cost_task_started",
                      extra={"task_id": task_id, "model": model,
                             "budget": self._budget})
            return tc

    def finish_task(self, task_id: str) -> TaskCost | None:
        with self._lock:
            tc = self._current.pop(task_id, None)
            self._totals.pop(task_id, None)
            if tc:
                tc.finished_at = time.time()
                self._flush(tc)
                log.debug("cost_task_finished",
                          extra=tc.to_dict())
            return tc

    def record(self, prompt_tokens: int = 0,
               completion_tokens: int = 0,
               task_id: str = "") -> None:
        with self._lock:
            tc: TaskCost | None = None
            if task_id and task_id in self._current:
                tc = self._current[task_id]
            elif len(self._current) == 1:
                tc = next(iter(self._current.values()))
            if tc is None:
                return

            tc.prompt_tok      += prompt_tokens
            tc.completion_tok  += completion_tokens
            self._totals[tc.task_id] = tc.total_tokens

            if self._budget > 0 and tc.total_tokens > self._budget:
                log.warning("cost_budget_exceeded",
                            extra={"task_id": tc.task_id,
                                   "spent": tc.total_tokens,
                                   "budget": self._budget})
                raise BudgetExceededError(tc.total_tokens, self._budget)

    def record_tool_call(self, task_id: str = "") -> None:
        with self._lock:
            tc: TaskCost | None = None
            if task_id and task_id in self._current:
                tc = self._current[task_id]
            elif len(self._current) == 1:
                tc = next(iter(self._current.values()))
            if tc:
                tc.tool_calls += 1

    def current_spend(self, task_id: str = "") -> int:
        with self._lock:
            if task_id:
                return self._totals.get(task_id, 0)
            if self._totals:
                return sum(self._totals.values())
            return 0

    def budget_remaining(self, task_id: str = "") -> int | None:
        if not self._budget:
            return None
        return max(0, self._budget - self.current_spend(task_id))

    def history(self, n: int = 50) -> list[dict]:
        if not self._log_path.exists():
            return []
        records = []
        try:
            for line in reversed(self._log_path.read_text(
                    encoding="utf-8").splitlines()):
                try:
                    records.append(json.loads(line))
                    if len(records) >= n:
                        break
                except Exception:
                    continue
        except Exception as _e:
            log.debug("cost_history_read_error", extra={"error": str(_e)[:80]})
        return list(reversed(records))

    def summary(self) -> dict:
        records = self.history(n=1000)
        if not records:
            return {"tasks": 0, "total_tokens": 0, "avg_tokens": 0,
                    "total_tool_calls": 0}
        total_tok  = sum(r.get("total_tokens", 0) for r in records)
        total_calls = sum(r.get("tool_calls", 0) for r in records)
        return {
            "tasks":             len(records),
            "total_tokens":      total_tok,
            "avg_tokens":        total_tok // len(records) if records else 0,
            "total_tool_calls":  total_calls,
        }

    def _flush(self, tc: TaskCost) -> None:
        if not self._log_enabled:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(tc.to_dict()) + "\n")
        except Exception as _e:
            log.debug("cost_flush_error", extra={"error": str(_e)[:80]})

_cost_tracker: CostTracker | None = None

def get_cost_tracker(workspace: Path | None = None,
                     budget: int = 0) -> CostTracker:
    global _cost_tracker
    if _cost_tracker is None:
        ws = workspace or Path.home() / ".uais"
        _cost_tracker = CostTracker(ws, budget=budget)
    return _cost_tracker
