from __future__ import annotations
import threading
import time
import dataclasses as _dc
from typing import Any

@_dc.dataclass
class BlackboardEntry:
    key: str; value: Any; entry_type: str = "fact"; author: str = "system"
    ts: float = _dc.field(default_factory=time.time); confidence: float = 1.0

class SharedBlackboard:
    def __init__(self) -> None:
        self._entries: dict[str, BlackboardEntry] = {}; self._lock = threading.RLock()
    def write(self, key: str, value: Any, entry_type: str = "fact", author: str = "system", confidence: float = 1.0) -> None:
        with self._lock: self._entries[key] = BlackboardEntry(key=key, value=value, entry_type=entry_type, author=author, confidence=confidence)
    def read(self, key: str, default: Any = None) -> Any:
        with self._lock:
            e = self._entries.get(key); return e.value if e else default
    def read_all(self, entry_type: str | None = None) -> list[BlackboardEntry]:
        with self._lock:
            return [e for e in self._entries.values() if not entry_type or e.entry_type == entry_type]
    def clear(self) -> None:
        with self._lock: self._entries.clear()
    def simulate(self, key: str, value: Any) -> dict:
        with self._lock:
            sim = {k: e.value for k, e in self._entries.items()}
            sim[key] = value
            return sim
    def to_context(self, max_entries: int = 20) -> str:
        with self._lock:
            if not self._entries: return ""
            lines = ["[Shared Blackboard]"]
            for e in list(self._entries.values())[-max_entries:]:
                lines.append(f"  [{e.entry_type}] {e.key}: {str(e.value)[:200]} (by {e.author})")
            return "\n".join(lines)
