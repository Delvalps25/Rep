from __future__ import annotations
import json
import threading
import time
import dataclasses as _dc
from pathlib import Path
from typing import Any

@_dc.dataclass
class PromptVariant:
    variant_id: str; role: str; text: str
    trials: int = 0; total_reward: float = 0.0
    @property
    def avg_reward(self) -> float: return self.total_reward / max(self.trials, 1)

class PromptEvolution:
    def __init__(self, workspace: Path):
        self._path = workspace / "logs" / "prompt_variants.json"
        self._variants: dict[str, list[PromptVariant]] = {}
        self._lock = threading.Lock()
        self._load()
    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for role, vs in data.items(): self._variants[role] = [PromptVariant(**v) for v in vs]
            except Exception: pass
    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({r: [_dc.asdict(v) for v in vs] for r, vs in self._variants.items()}, indent=2), encoding="utf-8")
        except Exception: pass
    def seed(self, role: str, base_prompt: str) -> None:
        with self._lock:
            if role not in self._variants or not self._variants[role]:
                self._variants[role] = [PromptVariant(variant_id=f"{role}_v0", role=role, text=base_prompt)]
                self._save()
    def select(self, role: str) -> str:
        import math
        with self._lock:
            vs = self._variants.get(role, [])
            if not vs: return ""
            total = sum(v.trials for v in vs) or 1
            return max(vs, key=lambda v: v.avg_reward + math.sqrt(2 * math.log(total) / max(v.trials, 1))).text
    def record(self, role: str, prompt_text: str, reward: float) -> None:
        with self._lock:
            for v in self._variants.get(role, []):
                if v.text == prompt_text: v.trials += 1; v.total_reward += reward; break
            self._save()
