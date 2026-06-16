import os
from __future__ import annotations
import json
import threading
import time
import hashlib
import dataclasses as _dc
from pathlib import Path
from typing import Any

_WF_COMPRESS_THRESHOLD = int(os.environ.get("UAIS_WF_COMPRESS_THRESHOLD", "3"))

@_dc.dataclass
class WorkflowPattern:
    pattern_hash: str; tool_sequence: list[str]; action_summary: str
    occurrences: int = 0; last_seen: float = _dc.field(default_factory=time.time)
    compressed: bool = False

class WorkflowCompressor:
    def __init__(self, workspace: Path):
        self._ws = workspace; self._patterns: dict[str, WorkflowPattern] = {}
        self._lock = threading.Lock(); self._path = workspace / "logs" / "workflow_patterns.json"
        self._load()
    def _load(self) -> None:
        if self._path.exists():
            try:
                for k, v in json.loads(self._path.read_text(encoding="utf-8")).items():
                    self._patterns[k] = WorkflowPattern(**v)
            except Exception: pass
    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({k: _dc.asdict(v) for k, v in self._patterns.items()}, indent=2), encoding="utf-8")
        except Exception: pass
    def record(self, steps: list[Any], arch_id: str = "") -> str | None:
        import os
        if len(steps) < 2: return None
        seq = [f"{s.tool}:{(s.action.split()[0].lower() if s.action else 'do')}" for s in steps]
        data = "|".join(seq) + (f"|{arch_id}" if arch_id else "")
        ph = hashlib.sha256(data.encode()).hexdigest()[:16]
        with self._lock:
            wp = self._patterns.get(ph)
            if wp: wp.occurrences += 1; wp.last_seen = time.time()
            else:
                wp = WorkflowPattern(pattern_hash=ph, tool_sequence=[s.tool for s in steps],
                    action_summary=" > ".join(s.action[:40] for s in steps), occurrences=1)
                self._patterns[ph] = wp
            self._save()
            if wp.occurrences >= _WF_COMPRESS_THRESHOLD and not wp.compressed:
                wp.compressed = True; self._save()
                tools = sorted(set(wp.tool_sequence))
                steps_md = "\n".join(f"{i+1}. {s.action}" for i, s in enumerate(steps))
                return f"---" + f"\nname: auto-{ph[:8]}\ndescription: Auto-pattern (seen {wp.occurrences}x)\ntools: [{', '.join(tools)}]\n---\n\n## Steps\n{steps_md}\n"
        return None
