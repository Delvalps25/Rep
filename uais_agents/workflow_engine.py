import os
import json
import time
import secrets
import enum as _enum
from pathlib import Path
from typing import Any, Callable, List, Dict, Optional
from uais_core.events import log

class StepStatus(_enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"

class WorkflowStep:
    def __init__(self, step_id: int, action: str, tool: str = "none", args: Dict = None):
        self.step_id = step_id
        self.action  = action
        self.tool    = tool
        self.args    = args or {}
        self.status  = StepStatus.PENDING
        self.result  = ""
        self.error   = ""

    def to_dict(self) -> Dict:
        return {
            "step_id": self.step_id,
            "action": self.action,
            "tool": self.tool,
            "args": self.args,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }

class WorkflowState:
    def __init__(self, task_id: str, task: str, steps: List[WorkflowStep], created_at: float, checkpoint_path: Path):
        self.task_id = task_id
        self.task = task
        self.steps = steps
        self.created_at = created_at
        self.checkpoint_path = checkpoint_path

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }

class WorkflowEngine:
    """
    Deterministic workflow execution engine.
    """

    def __init__(self, workspace: Path) -> None:
        self._ws = workspace / "workflows"
        self._ws.mkdir(parents=True, exist_ok=True)

    def create(self, task: str, raw_steps: List[Dict]) -> WorkflowState:
        task_id = f"wf_{int(time.time())}_{secrets.token_hex(4)}"
        steps   = [
            WorkflowStep(
                step_id = s.get("step", i + 1),
                action  = s.get("action", ""),
                tool    = s.get("tool", "none"),
                args    = s.get("args", {}),
            )
            for i, s in enumerate(raw_steps)
        ]
        state = WorkflowState(
            task_id=task_id, task=task, steps=steps,
            created_at=time.time(),
            checkpoint_path=self._ws / f"{task_id}.json",
        )
        self._checkpoint(state)
        return state

    def _checkpoint(self, state: WorkflowState) -> None:
        """Write state atomically: write tmp → rename."""
        if state.checkpoint_path is None:
            return
        tmp = state.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(state.checkpoint_path)

    _DESTRUCTIVE_TOOLS = frozenset({
        "shell", "write_file", "python_exec", "finetune",
        "train_model", "build_skill",
    })

    def snapshot_workspace(self, state: WorkflowState,
                           step: WorkflowStep,
                           workspace: Path) -> Optional[Path]:
        """Create a lightweight workspace snapshot."""
        if step.tool not in self._DESTRUCTIVE_TOOLS:
            return None
        snap_path = self._ws / f"{state.task_id}_snap_{step.step_id}.tar.gz"
        try:
            import tarfile
            _snap_limit = int(os.environ.get("UAIS_SNAP_FILES", "500"))
            _EXCLUDE_PATTERNS = frozenset({".log", ".tmp", ".pyc", ".pyo", ".o", ".so"})
            _EXCLUDE_DIRS = frozenset({"logs", "__pycache__", ".git", "node_modules"})

            def _file_priority(p: Path) -> tuple:
                import math
                try:
                    st = p.stat()
                    return (st.st_mtime, math.log(st.st_size + 1))
                except OSError:
                    return (0.0, 0.0)

            candidates = [
                p for p in workspace.rglob("*")
                if p.is_file()
                and p.suffix not in _EXCLUDE_PATTERNS
                and not any(part.startswith(".") for part in p.parts[-3:])
                and not any(part in _EXCLUDE_DIRS for part in p.relative_to(workspace).parts)
            ]
            candidates.sort(key=_file_priority, reverse=True)
            with tarfile.open(snap_path, "w:gz") as tf:
                for p in candidates[:_snap_limit]:
                    tf.add(p, arcname=str(p.relative_to(workspace)))
            return snap_path
        except Exception:
            return None

    def classify_error(self, error: str) -> str:
        err_lower = error.lower()
        TRANSIENT_SIGNALS = ("timeout", "connection", "network", "refused", "temporarily", "rate limit", "429", "503", "retry")
        FATAL_SIGNALS = ("permission denied", "access denied", "unauthorized", "no such file", "disk full", "quota exceeded", "killed", "segmentation fault")
        if any(s in err_lower for s in FATAL_SIGNALS):
            return "fatal"
        if any(s in err_lower for s in TRANSIENT_SIGNALS):
            return "transient"
        return "recoverable"

    def execute_step(self, state: WorkflowState, step: WorkflowStep,
                     executor_fn: Callable[[WorkflowStep], str],
                     replan_fn: Optional[Callable[[str, WorkflowStep], Optional[WorkflowStep]]] = None,
                     ) -> StepStatus:
        if step.status == StepStatus.SUCCESS:
            return step.status

        step.status = StepStatus.RUNNING
        self._checkpoint(state)

        try:
            step.result = executor_fn(step)
            step.status = StepStatus.SUCCESS
        except Exception as e:
            step.error = str(e)
            step.status = StepStatus.FAILURE
            # Logic for retries or replanning would go here

        self._checkpoint(state)
        return step.status
