import os
import time
import threading
import dataclasses as _dc
from pathlib import Path
from typing import Any, Dict, Optional

@_dc.dataclass
class A2ATask:
    """Represents a single A2A task (request + state)."""
    task_id:    str
    message:    str           # user-facing task description
    session_id: str           = ""
    status:     str           = "submitted"   # submitted|working|completed|failed|cancelled
    result:     str           = ""
    error:      str           = ""
    created_at: float         = _dc.field(default_factory=time.time)
    updated_at: float         = _dc.field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.task_id,
            "sessionId": self.session_id,
            "status": {"state": self.status},
            "history": [{"role": "user",   "parts": [{"text": self.message}]}]
                      + ([{"role": "agent", "parts": [{"text": self.result}]}]
                         if self.result else []),
            "error": self.error or None,
        }

class A2AServer:
    """
    A2A-compatible agent server mixin.
    """

    def __init__(self, hw: Any, workspace: Path) -> None:
        self._hw   = hw
        self._ws   = workspace
        self._tasks: Dict[str, A2ATask] = {}
        self._lock  = threading.Lock()

    def _a2a_auth_block(self) -> dict:
        use_oauth = bool(os.environ.get("UAIS_A2A_OAUTH"))
        oauth_server = os.environ.get("UAIS_A2A_OAUTH_SERVER", "").rstrip("/")
        use_bearer = bool(os.environ.get("UAIS_SLAVE_TOKEN"))
        if use_oauth and oauth_server:
            return {"authentication": {
                "schemes": ["oauth2"],
                "required": True,
                "oauth2": {
                    "authorizationUrl": f"{oauth_server}/authorize",
                    "tokenUrl":         f"{oauth_server}/token",
                    "pkce": True,
                    "scopes": {"agent:task": "Submit and manage agent tasks"},
                },
            }}
        return {"authentication": {
            "schemes": ["bearer"] if use_bearer else [],
            "required": use_bearer,
        }}

    def agent_card(self, base_url: str = "") -> dict:
        return {
            "name": "UAIS",
            "description": f"Unified AI Intelligence System - {self._hw.tier_label if hasattr(self._hw, 'tier_label') else 'Unknown'}",
            "url": base_url,
            "capabilities": {
                "tasks": True,
                "streaming": True
            },
            "auth": self._a2a_auth_block()
        }
