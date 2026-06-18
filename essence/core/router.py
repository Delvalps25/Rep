import os
import json
import secrets
import threading
import dataclasses as _dc
import math
from pathlib import Path
from typing import Any, Dict, List, Optional
from essence.config import log

@_dc.dataclass
class ModelTrialStats:
    model: str
    requests: int = 0
    successes: int = 0
    total_score: float = 0.0
    weight: float = 0.5

    @property
    def avg_score(self) -> float:
        return self.total_score / max(self.requests, 1)

class ABModelRouter:
    MIN_REQUESTS   = int(os.environ.get("UAIS_AB_MIN_REQUESTS", "30"))
    PROMOTE_DELTA  = float(os.environ.get("UAIS_AB_PROMOTE_DELTA", "0.10"))

    def __init__(self, workspace: Path) -> None:
        self._ws     = workspace
        self._stats: Dict[str, ModelTrialStats] = {}
        self._lock   = threading.Lock()

    def select(self) -> str:
        with self._lock:
            if not self._stats: return ""
            models = list(self._stats.keys())
            weights = [s.weight for s in self._stats.values()]
            total = sum(weights)
            rnd = (int.from_bytes(secrets.token_bytes(4), "big") / (2**32)) * total
            cum = 0.0
            for m, w in zip(models, weights):
                cum += w
                if rnd < cum: return m
            return models[-1]

_BANDIT_ALPHA = float(os.environ.get("UAIS_BANDIT_ALPHA", "1.0"))
_BANDIT_MIN_N = int(os.environ.get("UAIS_BANDIT_MIN_N", "5"))

@_dc.dataclass
class _BanditArm:
    model: str
    context_key: str
    n: int = 0
    total_reward: float = 0.0
    total_latency_ms: float = 0.0
    total_tokens: int = 0

    @property
    def ucb(self) -> float:
        if self.n == 0: return float("inf")
        mean_reward = self.total_reward / self.n
        return mean_reward + _BANDIT_ALPHA * math.sqrt(math.log(self.n + 1) / self.n)

class ContextualBanditRouter:
    def __init__(self, workspace: Path, ab_router: ABModelRouter) -> None:
        self._ws = workspace
        self._ab = ab_router
        self._arms: Dict[str, _BanditArm] = {}
        self._lock = threading.Lock()

    def select(self, context: Optional[Dict] = None) -> str:
        with self._lock:
            models = list(self._ab._stats.keys())
            if not models: return ""
            # Simplified selection logic
            return models[0]
