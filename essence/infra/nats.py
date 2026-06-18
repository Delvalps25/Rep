import threading
import asyncio
from typing import Any, Optional
from essence.config import log

try:
    import nats as _nats_mod
    _NATS = True
except ImportError:
    _NATS = False

class NATSEventBus:
    def __init__(self, url: str, stream: str = "UAIS") -> None:
        self._url    = url
        self._stream = stream
        self._nc:    Any = None
        self._js:    Any = None
        self._ready  = False

    async def connect(self) -> None:
        if not _NATS: return
        try:
            self._nc = await _nats_mod.connect(self._url)
            self._js = self._nc.jetstream()
            self._ready = True
            log.info("nats_connected", extra={"url": self._url})
        except Exception as e:
            log.warning("nats_connect_failed", extra={"error": str(e)})
