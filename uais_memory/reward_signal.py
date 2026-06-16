from __future__ import annotations
import json
import threading
from typing import Any
from uais_memory.memory import Memory

class RewardSignal:
    def __init__(self, task_id: str, score: float, evidence: str = ""):
        self.task_id = task_id
        self.score   = score
        self.evidence = evidence

def compute_reward(result: Any, target: Any = None) -> float:
    if result is None: return 0.0
    if result == target: return 1.0
    return 0.5
