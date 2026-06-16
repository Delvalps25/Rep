import json
import hashlib
import time
import sys
import threading
import dataclasses as _dc
from typing import Any, Dict, Optional

@_dc.dataclass
class CapabilityToken:
    """A one-time-use authorisation for a specific tool call."""
    tool_name:  str
    arg_hash:   str       # sha256 of json(args) — binds token to exact call
    expires_at: float     # monotonic time
    granted_by: str = "auto"  # "auto" | "user" | "master"
    used:       bool = False

class CapabilityPolicy:
    """
    Pre-call capability token system.
    """
    DESTRUCTIVE = {"shell", "write_file", "python_exec", "train_model", "finetune", "ingest"}

    def __init__(self, autonomy_level: int = 1, ttl_s: float = 30.0) -> None:
        self._level  = autonomy_level
        self._ttl    = ttl_s
        self._tokens: Dict[str, CapabilityToken] = {}
        self._lock   = threading.Lock()

    def _arg_hash(self, args: Dict) -> str:
        return hashlib.sha256(
            json.dumps(args, sort_keys=True).encode()).hexdigest()[:16]

    def request_grant(self, tool_name: str, args: Dict,
                      interactive: bool = True) -> Optional[CapabilityToken]:
        ah    = self._arg_hash(args)
        token = CapabilityToken(
            tool_name=tool_name, arg_hash=ah,
            expires_at=time.monotonic() + self._ttl)

        if self._level == 2:
            token.granted_by = "auto"
            with self._lock:
                self._tokens[f"{tool_name}:{ah}"] = token
            return token

        if self._level >= 1 and tool_name not in self.DESTRUCTIVE:
            token.granted_by = "auto"
            with self._lock:
                self._tokens[f"{tool_name}:{ah}"] = token
            return token

        if interactive and sys.stdin.isatty():
            prompt_str = (f"\n[CapabilityPolicy] Grant "
                          f"'{tool_name}'({json.dumps(args)[:80]})? [y/N] ")
            try:
                ans = input(prompt_str).strip().lower()
            except EOFError:
                ans = "n"
            if ans in ("y", "yes"):
                token.granted_by = "user"
                with self._lock:
                    self._tokens[f"{tool_name}:{ah}"] = token
                return token
        return None
