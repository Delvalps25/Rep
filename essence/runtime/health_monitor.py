from __future__ import annotations
import os
import threading
import time
import dataclasses as _dc
from typing import Any
from essence.core.events import log
from essence.core.providers import _ping
from essence.infra.circuit_breaker import CIRCUIT_BREAKERS

_HEALTH_INTERVAL = int(os.environ.get("UAIS_HEALTH_INTERVAL", "30"))
_HEALTH_TIMEOUT  = int(os.environ.get("UAIS_HEALTH_TIMEOUT",  "5"))

@_dc.dataclass
class BackendHealth:
    name:       str
    url:        str
    healthy:    bool  = True
    last_check: float = 0.0
    latency_ms: float = 0.0
    failures:   int   = 0

class HealthMonitor:
    def __init__(self) -> None:
        self._backends: dict[str, BackendHealth] = {}
        self._lock      = threading.Lock()
        self._stop      = threading.Event()
        self._thread:   threading.Thread | None = None

    def register(self, name: str, url: str) -> None:
        with self._lock:
            self._backends[name] = BackendHealth(name=name, url=url)

    def _probe(self, bh: BackendHealth) -> None:
        t0      = time.monotonic()
        healthy = _ping(bh.url, t=_HEALTH_TIMEOUT)
        latency = (time.monotonic() - t0) * 1000
        cb      = CIRCUIT_BREAKERS.get(bh.name)
        with self._lock:
            bh.last_check = time.time()
            bh.latency_ms = latency
            if healthy:
                bh.healthy  = True
                bh.failures = 0
                cb.record_success()
            else:
                bh.healthy   = False
                bh.failures += 1
                cb.record_failure()
                log.warning("health_probe_failed",
                            extra={"backend": bh.name, "url": bh.url,
                                   "failures": bh.failures})

    def _loop(self) -> None:
        while not self._stop.wait(timeout=_HEALTH_INTERVAL):
            with self._lock:
                snapshot = list(self._backends.values())
            for bh in snapshot:
                try:
                    self._probe(bh)
                except Exception as _e:
                    log.debug("health_probe_error",
                              extra={"backend": bh.name, "error": str(_e)[:80]})

    def start(self) -> None:
        self._stop.clear()
        with self._lock:
            snapshot = list(self._backends.values())
        for bh in snapshot:
            try:
                self._probe(bh)
            except Exception:
                pass
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                         name="uais-health-monitor")
        self._thread.start()
        log.info("health_monitor_started",
                 extra={"interval": _HEALTH_INTERVAL,
                        "backends": list(self._backends)})

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> list[dict]:
        with self._lock:
            return [_dc.asdict(bh) for bh in self._backends.values()]

    def all_healthy(self) -> bool:
        with self._lock:
            return all(bh.healthy for bh in self._backends.values())

HEALTH_MONITOR = HealthMonitor()
