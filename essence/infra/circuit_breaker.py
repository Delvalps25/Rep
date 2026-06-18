import time
import threading
from typing import Any, Dict, List, Optional
from essence.config import log

class CircuitBreaker:
    def __init__(self, name: str, threshold: int = 5, window: int = 60):
        self.name = name
        self.threshold = threshold
        self.window = window
        self._failures = []
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.time()
            self._failures = [f for f in self._failures if now - f < self.window]
            return len(self._failures) < self.threshold

    def record_failure(self):
        with self._lock:
            self._failures.append(time.time())

CIRCUIT_BREAKERS: Dict[str, CircuitBreaker] = {}
