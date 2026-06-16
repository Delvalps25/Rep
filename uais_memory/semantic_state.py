from __future__ import annotations
import json
import os
import secrets
import time
import threading
import dataclasses as _dc
from pathlib import Path
from typing import Any
from uais_core.events import log
from uais_core.infra.fast_json import _fast_loads

@_dc.dataclass
class SemanticFact:
    entity:      str
    relation:    str
    attribute:   str
    value:       str
    confidence:  float = 1.0
    source:      str   = "inferred"
    ts:          float = _dc.field(default_factory=time.time)
    fact_id:     str   = _dc.field(default_factory=lambda: secrets.token_hex(6))
    domain_lens: str | None = None
    finding_id:  str | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict:
        return _dc.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SemanticFact":
        return cls(**{k: v for k, v in d.items() if k in {
            "entity","relation","attribute","value","confidence","source","ts","fact_id"}})

    def key(self) -> tuple:
        return (self.entity, self.relation, self.attribute)

class SemanticStateStore:
    def __init__(self, path: Path) -> None:
        self._path  = path
        self._facts: list[SemanticFact] = []
        self._lock  = threading.RLock()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._facts = [SemanticFact.from_dict(d) for d in raw]
            except Exception as _e:
                log.debug("semantic_state_load_error", extra={"error": str(_e)[:120]})

    _MAX_FACTS    = int(os.environ.get("UAIS_SSS_MAX_FACTS", "5000"))
    _PRUNE_CONF   = float(os.environ.get("UAIS_SSS_PRUNE_CONF", "0.25"))
    _PRUNE_DAYS   = int(os.environ.get("UAIS_SSS_PRUNE_DAYS", "30"))

    def _save(self) -> None:
        cutoff_ts = time.time() - self._PRUNE_DAYS * 86400
        self._facts = [
            f for f in self._facts
            if not (f.confidence < self._PRUNE_CONF and f.ts < cutoff_ts)
        ]
        if len(self._facts) > self._MAX_FACTS:
            self._facts = sorted(self._facts,
                                  key=lambda f: (-f.confidence, -f.ts))[:self._MAX_FACTS]
        tmp = self._path.with_suffix(".tmp")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(
            json.dumps([f.to_dict() for f in self._facts], indent=2, default=str),
            encoding="utf-8")
        tmp.replace(self._path)

    def assert_fact(self, entity: str, relation: str, attribute: str,
                    value: str, confidence: float = 1.0,
                    source: str = "inferred") -> bool:
        with self._lock:
            conflict = False
            for f in self._facts:
                if f.key() == (entity, relation, attribute):
                    if f.value != value:
                        conflict = True
                        if confidence >= f.confidence:
                            f.value      = value
                            f.confidence = confidence
                            f.source     = source
                            f.ts         = time.time()
                    else:
                        f.confidence = max(f.confidence, confidence)
                        f.ts         = time.time()
                    self._save()
                    return conflict
            self._facts.append(SemanticFact(
                entity=entity, relation=relation, attribute=attribute,
                value=value, confidence=confidence, source=source))
            self._save()
            return False

    def query(self, entity: str | None = None,
              relation: str | None = None,
              attribute: str | None = None) -> list[SemanticFact]:
        with self._lock:
            results = []
            for f in self._facts:
                if entity    and f.entity    != entity:    continue
                if relation  and f.relation  != relation:  continue
                if attribute and f.attribute != attribute: continue
                results.append(f)
            return sorted(results, key=lambda f: f.ts, reverse=True)

    def conflicts(self) -> list[tuple[str, list[SemanticFact]]]:
        with self._lock:
            from collections import defaultdict
            groups: dict[tuple, list[SemanticFact]] = defaultdict(list)
            for f in self._facts:
                groups[f.key()].append(f)
            return [
                (f"{k[0]}.{k[1]}.{k[2]}", facts)
                for k, facts in groups.items()
                if len({f.value for f in facts}) > 1
            ]

    def resolve_conflict(self, entity: str, relation: str, attribute: str,
                         keep_value: str) -> bool:
        with self._lock:
            before = len(self._facts)
            self._facts = [
                f for f in self._facts
                if not (f.key() == (entity, relation, attribute) and f.value != keep_value)
            ]
            changed = len(self._facts) < before
            if changed:
                self._save()
            return changed

    def to_prompt_block(self, max_facts: int = 40) -> str:
        with self._lock:
            top = sorted(self._facts, key=lambda f: (-f.confidence, -f.ts))[:max_facts]
        if not top:
            return ""
        lines = ["[Semantic state]"]
        for f in top:
            conf = f"({f.confidence:.1f})" if f.confidence < 1.0 else ""
            lines.append(f"  {f.entity}.{f.relation}.{f.attribute} = {f.value}{conf}")
        return "\n".join(lines)
