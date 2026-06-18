import threading
import time
from typing import Any, Dict, Optional

class RequestDeduplicator:
    def __init__(self, ttl: int = 300):
        self.ttl = ttl
        self._cache = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                entry = self._cache[key]
                if time.time() - entry['ts'] < self.ttl:
                    return entry['res']
            return None

    def store(self, key: str, res: Any):
        with self._lock:
            self._cache[key] = {'res': res, 'ts': time.time()}

class ConcurrencyLimiter:
    def __init__(self, route: str, limit: int = 10):
        self._sem = threading.Semaphore(limit)
    def __enter__(self): self._sem.acquire()
    def __exit__(self, *args): self._sem.release()
