import os
import threading
import time
import collections as _coll
from typing import tuple

_RL_DEFAULTS = {
    "chat":     int(os.environ.get("UAIS_RL_CHAT",  "60")),
    "shell":    int(os.environ.get("UAIS_RL_SHELL", "20")),
    "agent":    int(os.environ.get("UAIS_RL_AGENT", "10")),
    "admin":    int(os.environ.get("UAIS_RL_ADMIN", "30")),
}

class RateLimiter:
    _WINDOW = 60.0
    _SWEEP_EVERY = 1000

    def __init__(self) -> None:
        self._windows: dict[str, _coll.deque] = {}
        self._lock  = threading.Lock()
        self._calls = 0

    def _sweep(self) -> None:
        cutoff = time.monotonic() - self._WINDOW
        dead   = [k for k, dq in self._windows.items()
                  if not dq or dq[-1] < cutoff]
        for k in dead:
            self._windows.pop(k, None)

    def check(self, user_id: str, route: str, limit: int | None = None) -> tuple[bool, float]:
        if limit is None:
            try:
                from uais_core.infra.valkey import get_config
                _cfg = get_config()
                limit = getattr(_cfg, f"rl_{route}", None) or _RL_DEFAULTS.get(route, 60)
            except Exception:
                limit = _RL_DEFAULTS.get(route, 60)
        if limit <= 0:
            return True, 0.0

        key = f"{user_id}:{route}"
        now = time.monotonic()
        cutoff = now - self._WINDOW

        with self._lock:
            self._calls += 1
            if self._calls % self._SWEEP_EVERY == 0:
                self._sweep()
            dq = self._windows.setdefault(key, _coll.deque())
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= limit:
                retry_after = self._WINDOW - (now - dq[0])
                return False, max(0.0, retry_after)
            dq.append(now)
            return True, 0.0

    def reset(self, user_id: str, route: str) -> None:
        key = f"{user_id}:{route}"
        with self._lock:
            self._windows.pop(key, None)

RATE_LIMITER = RateLimiter()
