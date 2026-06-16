from __future__ import annotations
import os
import dataclasses as _dc
from pathlib import Path
from typing import Any, List as list
from uais_core.events import log
from uais_core.config import SOP_DIR

@_dc.dataclass
class SOPDoc:
    path:     Path
    name:     str
    triggers: list[str]
    priority: str
    content:  str

    def matches(self, task: str) -> bool:
        task_lower = task.lower()
        return any(t.lower() in task_lower for t in self.triggers) or \
               self.name.lower().replace("_", " ") in task_lower

class SOPLoader:
    def __init__(self, sop_dir: str | Path | None = None) -> None:
        dirs = []
        if sop_dir:
            dirs.append(Path(sop_dir))
        if SOP_DIR:
            dirs.append(Path(SOP_DIR))
        self._dirs  = dirs
        self._docs:  list[SOPDoc] = []
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for d in self._dirs:
            if not d.exists():
                continue
            for p in sorted(d.glob("*.md")):
                try:
                    self._docs.append(self._parse(p))
                except Exception as _e:
                    log.debug("sop_load_error",
                              extra={"path": str(p), "error": str(_e)[:80]})

    @staticmethod
    def _parse(path: Path) -> SOPDoc:
        text    = path.read_text(encoding="utf-8", errors="replace")
        triggers: list[str] = []
        priority = "medium"
        content  = text
        if text.startswith("---"):
            end = text.find("---", 3)
            if end > 0:
                fm_raw = text[3:end].strip()
                content = text[end + 3:].strip()
                for line in fm_raw.splitlines():
                    if line.startswith("triggers:"):
                        raw = line.split(":", 1)[1].strip()
                        raw = raw.strip("[]")
                        triggers = [t.strip().strip('"').strip("'")
                                    for t in raw.split(",") if t.strip()]
                    elif line.startswith("priority:"):
                        priority = line.split(":", 1)[1].strip()
        if not triggers:
            triggers = [path.stem.replace("_", " ").replace("-", " ")]
        return SOPDoc(
            path=path,
            name=path.stem,
            triggers=triggers,
            priority=priority,
            content=content,
        )

    def relevant(self, task: str, max_docs: int = 2) -> str:
        self._load()
        if not self._docs:
            return ""
        priority_order = {"high": 0, "medium": 1, "low": 2}
        matched = sorted(
            [d for d in self._docs if d.matches(task)],
            key=lambda d: priority_order.get(d.priority, 1)
        )[:max_docs]
        if not matched:
            return ""
        parts = ["\n# Relevant Standard Operating Procedures\n"]
        for doc in matched:
            parts.append(f"## {doc.name.replace('_', ' ').title()}\n")
            parts.append(doc.content[:1500])
            parts.append("\n")
        return "\n".join(parts)

    def list_all(self) -> list[dict]:
        self._load()
        return [{"name": d.name, "triggers": d.triggers,
                 "priority": d.priority, "path": str(d.path)}
                for d in self._docs]

_sop_loader: SOPLoader | None = None

def get_sop_loader(sop_dir: str | Path | None = None) -> SOPLoader:
    global _sop_loader
    if _sop_loader is None:
        _sop_loader = SOPLoader(sop_dir)
    return _sop_loader
