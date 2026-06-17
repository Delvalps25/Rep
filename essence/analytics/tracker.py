import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

class ExperimentTracker:
    """
    Unified experiment logging interface.
    Priority: W&B (WANDB_API_KEY set) → MLflow (MLFLOW_TRACKING_URI set)
              → TensorBoard (tensorboard installed) → local JSONL fallback.
    """
    def __init__(self, workspace: Path):
        self._ws      = workspace
        self._backend = "jsonl"
        self._run_id  = ""
        self._run: Any = None
        self._log_path: Path | None = None
        self._tb_writer: Any = None
        # Detect best available backend
        if os.environ.get("WANDB_API_KEY"):
            try:
                import wandb
                self._backend = "wandb"
            except ImportError: pass
        if self._backend == "jsonl" and os.environ.get("MLFLOW_TRACKING_URI"):
            try:
                import mlflow
                self._backend = "mlflow"
            except ImportError: pass
        if self._backend == "jsonl":
            try:
                from torch.utils.tensorboard import SummaryWriter
                self._backend = "tensorboard"
            except ImportError: pass

    def start_run(self, name: str, tags: Optional[Dict] = None) -> str:
        self._run_id = name
        tags = tags or {}
        # Backend specific initialization would go here
        return self._run_id

    def log_metrics(self, metrics: Dict[str, Any], step: Optional[int] = None) -> None:
        pass
