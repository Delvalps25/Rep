import json
import time
import hashlib
import threading
import os
from pathlib import Path
from typing import Any, Dict, Optional
import contextvars as _cv
import secrets
from essence.config import log

_request_ctx: "_cv.ContextVar[dict]" = _cv.ContextVar(
    "uais_request_ctx",
    default={"user_id": "anon", "session_id": "", "request_id": ""}
)

def get_request_context() -> dict:
    return _request_ctx.get()

def set_request_context(user_id: str = "anon",
                         session_id: str = "",
                         request_id: str = "") -> "_cv.Token":
    return _request_ctx.set({
        "user_id":    user_id,
        "session_id": session_id,
        "request_id": request_id or secrets.token_hex(8),
    })

def _fast_dumps(data: Any, **kwargs) -> str:
    return json.dumps(data, **kwargs)

class AuditLog:
    def __init__(self, workspace: Path) -> None:
        self._path      = workspace / "logs" / "audit.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock      = threading.Lock()

    def _last_hash(self) -> str:
        if not self._path.exists():
            return "0" * 64
        try:
            last_line = ""
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last_line = line.strip()
            if last_line:
                return json.loads(last_line).get("entry_hash", "0" * 64)
        except Exception:
            pass
        return "0" * 64

    def append(self, event_type: str, data: dict) -> None:
        if not (os.environ.get("UAIS_AUDIT", "0") == "1"):
            return
        with self._lock:
            prev = self._last_hash()
            ctx = get_request_context()
            entry: dict = {
                "ts":         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "event_type": event_type,
                "user_id":    ctx.get("user_id", "anon"),
                "session_id": ctx.get("session_id", ""),
                "request_id": ctx.get("request_id", ""),
                "data":       data,
                "prev_hash":  prev,
            }
            entry_str  = _fast_dumps(entry, sort_keys=True, default=str)
            entry_hash = hashlib.sha256(entry_str.encode()).hexdigest()
            entry["entry_hash"] = entry_hash
            line = _fast_dumps(entry, default=str) + "\n"
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)
