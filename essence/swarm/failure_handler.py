import os
import json
import time
import threading
import enum as _enum
import dataclasses as _dc
from pathlib import Path
from typing import Dict, Optional, Any

class DecisionPriority(_enum.Enum):
    INFO     = 0
    LOW      = 1
    MEDIUM   = 2
    HIGH     = 3
    CRITICAL = 4

@_dc.dataclass
class Decision:
    decision_id: str
    tool_name:   str
    args:        dict
    priority:    DecisionPriority
    reason:      str
    created_at:  float
    expires_at:  float
    approved:    Optional[bool] = None   # None = pending
    rejected_reason: str     = ""
    session_id:  str         = ""

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "tool_name":   self.tool_name,
            "args":        self.args,
            "priority":    self.priority.value,
            "reason":      self.reason,
            "created_at":  self.created_at,
            "expires_at":  self.expires_at,
            "approved":    self.approved,
            "rejected_reason": self.rejected_reason,
            "session_id":  self.session_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        dd = cls(
            decision_id=d["decision_id"],
            tool_name=d["tool_name"],
            args=d.get("args", {}),
            priority=DecisionPriority(d.get("priority", 1)),
            reason=d.get("reason", ""),
            created_at=d.get("created_at", 0.0),
            expires_at=d.get("expires_at", 0.0),
            session_id=d.get("session_id", ""),
        )
        dd.approved         = d.get("approved")
        dd.rejected_reason  = d.get("rejected_reason", "")
        return dd

class DecisionQueue:
    """
    File-backed decision queue for human-in-the-loop approvals.
    """

    _PRIORITY_RULES: Dict[str, DecisionPriority] = {
        "shell":       DecisionPriority.HIGH,
        "python_exec": DecisionPriority.HIGH,
        "write_file":  DecisionPriority.MEDIUM,
        "train_model": DecisionPriority.MEDIUM,
        "finetune":    DecisionPriority.HIGH,
        "ingest":      DecisionPriority.LOW,
        "web_search":  DecisionPriority.INFO,
        "read_file":   DecisionPriority.INFO,
    }

    def __init__(self, workspace: Path, default_ttl: float = 300.0) -> None:
        self._path       = workspace / "logs" / "decisions.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock       = threading.Lock()
        self._default_ttl = default_ttl
        self._cache: Dict[str, Decision] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try:
                d = Decision.from_dict(json.loads(line))
                self._cache[d.decision_id] = d
            except Exception:
                pass

    def _flush(self) -> None:
        """Rewrite the decision log from cache."""
        with self._lock:
            lines = [json.dumps(d.to_dict()) for d in self._cache.values()]
            self._path.write_text("\n".join(lines) + ("\n" if lines else ""),
                                   encoding="utf-8")

    def classify_priority(self, tool_name: str, args: dict) -> DecisionPriority:
        base = self._PRIORITY_RULES.get(tool_name, DecisionPriority.MEDIUM)
        if tool_name == "shell":
            cmd = args.get("command", "")
            if any(k in cmd for k in ("rm ", "drop ", "delete ", "format ", "mkfs", "dd if=", "> /dev/")):
                return DecisionPriority.CRITICAL
        return base

    def enqueue(self, tool_name: str, args: dict,
                reason: str = "", session_id: str = "") -> Decision:
        import secrets
        decision_id = secrets.token_hex(8)
        priority = self.classify_priority(tool_name, args)
        decision = Decision(
            decision_id=decision_id,
            tool_name=tool_name,
            args=args,
            priority=priority,
            reason=reason,
            created_at=time.time(),
            expires_at=time.time() + self._default_ttl,
            session_id=session_id
        )
        with self._lock:
            self._cache[decision_id] = decision
        self._flush()
        return decision
