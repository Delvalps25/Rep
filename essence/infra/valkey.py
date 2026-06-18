import os
import json
from typing import Any, Dict, Optional
from essence.config import log

try:
    import redis as _redis_mod
except ImportError:
    _redis_mod = None

class ValkeySessionStore:
    _TTL = int(os.environ.get("UAIS_SESSION_TTL", "3600"))

    def __init__(self, url: str) -> None:
        if _redis_mod:
            self._client = _redis_mod.from_url(url, decode_responses=True)
            log.info("valkey_session_store_connected", extra={"url": url.split("@")[-1]})
        else:
            self._client = None
            log.warning("valkey_missing", extra={"detail": "redis-py not installed"})

    def get(self, session_id: str) -> Optional[Dict]:
        if not self._client: return None
        try:
            raw = self._client.get(f"uais:session:{session_id}")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    def set(self, session_id: str, data: Dict) -> None:
        if not self._client: return
        try:
            self._client.setex(f"uais:session:{session_id}", self._TTL, json.dumps(data, default=str))
        except Exception:
            pass
