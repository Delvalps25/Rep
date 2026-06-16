from __future__ import annotations
import json
import os
import threading
import time
import re
import urllib.request
from pathlib import Path
from typing import Any
from uais_core.events import log
from uais_core.config import UAIS_VERSION, TEAM_ID
from uais_memory.vector_backends import MemoryBackend, _make_memory_backend
from uais_memory.episodic import EpisodicStore
from uais_memory.semantic_state import SemanticStateStore
from uais_agents.specialist import AgentRole
from uais_core.infra.schema_registry import SCHEMA_REGISTRY
from uais_core.vault.secrets import SecretsVault, _workspace_root

class Memory:
    def __init__(self, workspace: Path, tier: int = 0,
                 working_window: int = 20,
                 team_id: str | None = None) -> None:
        _tid = (team_id or TEAM_ID).strip()
        if _tid and _tid != "local":
            _team_ws = workspace / "team" / _tid
            _team_ws.mkdir(parents=True, exist_ok=True)
            workspace = _team_ws
        self._team_id  = _tid
        self._ws       = workspace
        self._mem_dir  = workspace / "memory"
        self._sess_dir = workspace / "sessions"
        self._mem_dir.mkdir(parents=True, exist_ok=True)
        self._sess_dir.mkdir(parents=True, exist_ok=True)
        self._tier     = tier
        self._working_window = working_window

        self._working: list[dict] = []
        self._working_lock = threading.Lock()
        self._episodic_path = self._mem_dir / "episodic.jsonl"

        self._kv_path  = self._mem_dir / "kv.json"
        self._kv: dict[str, Any] = {}
        self._kv_lock  = threading.Lock()
        self._load_kv()

        self._backend: MemoryBackend = _make_memory_backend(workspace, tier)

        self._graph_path = self._mem_dir / "semantic_graph.json"
        self._graph: dict[str, list[str]] = {}
        self._load_graph()

        self._profile_path = self._mem_dir / "user_profile.json"
        self._profile: dict[str, Any] = {}
        self._profile_lock = threading.Lock()
        self._load_profile()

    def _load_graph(self) -> None:
        if self._graph_path.exists():
            try:
                self._graph = json.loads(
                    self._graph_path.read_text(encoding="utf-8"))
            except Exception:
                self._graph = {}

    def _save_graph(self) -> None:
        tmp = self._graph_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._graph, indent=2), encoding="utf-8")
        tmp.replace(self._graph_path)

    _PROFILE_SCHEMA = {
        "name": "", "occupation": "", "location": "", "timezone": "",
        "communication_style": "", "primary_language": "en",
        "current_projects": [],
        "preferences": {},
        "goals": [],
        "notes": "",
    }

    def _load_profile(self) -> None:
        if self._profile_path.exists():
            try:
                with self._profile_lock:
                    self._profile = json.loads(
                        self._profile_path.read_text(encoding="utf-8"))
                return
            except Exception as _e:
                log.debug("memory_profile_load_error",
                          extra={"path": str(self._profile_path), "error": str(_e)[:120]})
        with self._profile_lock:
            self._profile = dict(self._PROFILE_SCHEMA)

    def _save_profile(self) -> None:
        tmp = self._profile_path.with_suffix(".tmp")
        with self._profile_lock:
            tmp.write_text(json.dumps(self._profile, indent=2, default=str),
                           encoding="utf-8")
        tmp.replace(self._profile_path)

    def update_profile(self, updates: dict[str, Any]) -> None:
        with self._profile_lock:
            for k, v in updates.items():
                if k not in self._PROFILE_SCHEMA:
                    continue
                existing = self._profile.get(k)
                if isinstance(existing, list) and isinstance(v, list):
                    merged = list(dict.fromkeys(existing + v))
                    self._profile[k] = merged[:20]
                elif isinstance(existing, dict) and isinstance(v, dict):
                    self._profile[k] = {**existing, **v}
                else:
                    self._profile[k] = v
        self._save_profile()

    def profile_block(self) -> str:
        with self._profile_lock:
            p = dict(self._profile)
        if not any(v for v in p.values()):
            return ""
        lines = ["[User profile]"]
        for k, v in p.items():
            if not v:
                continue
            if isinstance(v, list):
                lines.append(f"  {k}: {', '.join(str(i) for i in v[:5])}")
            elif isinstance(v, dict):
                for dk, dv in list(v.items())[:5]:
                    lines.append(f"  {k}.{dk}: {dv}")
            else:
                lines.append(f"  {k}: {str(v)[:120]}")
        return "\n".join(lines)

    def working_add(self, text: str, source: str = "chat") -> None:
        with self._working_lock:
            self._working.append({"text": text, "ts": time.time(),
                                   "source": source})
            if len(self._working) > self._working_window * 2:
                self._working = self._working[-self._working_window:]
            should_consolidate = (
                len(self._working) >= self._working_window
                and not getattr(self, "_consolidating", False)
            )
        if should_consolidate:
            self._consolidating = True
            _aref = getattr(self, "_agent_ref", None)
            threading.Thread(
                target=self._auto_consolidate, args=(_aref,), daemon=True).start()

    def _auto_consolidate(self, agent_ref: Any = None) -> None:
        try:
            with self._working_lock:
                entries = list(self._working)
            self.consolidate()
            if not entries:
                return
            consolidator = None
            if agent_ref is not None and self._tier >= 1:
                pool = getattr(agent_ref, "_specialist_pool", {})
                consolidator = pool.get(AgentRole.CONSOLIDATOR) if pool else None

            if consolidator:
                combined = " | ".join(e["text"][:200] for e in entries[-12:])
                extraction_prompt = (
                    "You are a memory extraction assistant.\n"
                    "Given this conversation snippet, extract two things:\n"
                    "1. A JSON list (key 'facts') of 0-3 durable facts worth "
                    "remembering long-term. If nothing is worth keeping, use [].\n"
                    "2. A JSON object (key 'profile') with any UserProfile fields "
                    "you can infer: name, occupation, location, timezone, "
                    "communication_style, primary_language, current_projects (list), "
                    "preferences (dict), goals (list), notes. Only include fields "
                    "with confident values; omit the rest.\n"
                    "Return ONLY valid JSON: "
                    '{"facts": [...], "profile": {...}}\n\n'
                    f"Snippet:\n{combined}"
                )
                try:
                    raw = consolidator.run(extraction_prompt)
                    clean = re.sub(r"```[a-zA-Z]*", "", raw).strip()
                    extracted = json.loads(clean)
                    _vok, _verr = SCHEMA_REGISTRY.validate("consolidation_output", extracted)
                    if not _vok:
                        log.debug("consolidation_schema_mismatch", extra={"error": _verr[:80]})
                    for fact in extracted.get("facts", []):
                        if isinstance(fact, str) and fact.strip():
                            self._backend.store(
                                fact[:500],
                                {"layer": "semantic", "type": "llm_extracted"})
                    if agent_ref is not None:
                        _sss = getattr(agent_ref, "_semantic_state", None)
                        for t in extracted.get("triples", [])[:20]:
                            if not isinstance(t, dict): continue
                            try:
                                _sss.assert_fact(
                                    entity    = str(t.get("entity",    "user")),
                                    relation  = str(t.get("relation",  "note")),
                                    attribute = str(t.get("attribute", "fact")),
                                    value     = str(t.get("value",     ""))[:300],
                                    confidence= float(t.get("confidence", 0.7)),
                                    source    = "auto_consolidation",
                                )
                            except Exception:
                                pass
                    profile_updates = extracted.get("profile", {})
                    if profile_updates and isinstance(profile_updates, dict):
                        self.update_profile(profile_updates)
                except Exception as e:
                    log.debug("llm_extraction_failed", extra={"error": str(e)[:80]})
                    self._backend.store(
                        combined[:500],
                        {"layer": "semantic", "type": "bulk_fallback"})
            else:
                _SIGNAL_WORDS = frozenset([
                    "remember", "always", "never", "prefer", "name", "called",
                    "version", "deadline", "project", "todo", "goal", "important",
                    "password", "key", "config", "setting",
                ])
                for entry in entries:
                    words = set(entry["text"].lower().split())
                    score = sum(1 for w in words if w in _SIGNAL_WORDS)
                    if "?" in entry["text"]:
                        score += 1
                    if score >= 2:
                        self._backend.store(
                            entry["text"][:500],
                            {"layer": "semantic", "type": "keyword_promoted",
                             "source": entry.get("source", "")})
        finally:
            self._consolidating = False

    def working_context(self, k: int = 5) -> list[str]:
        with self._working_lock:
            return [e["text"] for e in self._working[-k:]]

    def _get_ep_store(self) -> EpisodicStore:
        if not hasattr(self, "_ep_store") or self._ep_store is None:
            self._ep_store = EpisodicStore(self._ws)
        return self._ep_store

    def record_episode(self, text: str, metadata: dict | None = None) -> None:
        try:
            self._get_ep_store().record(
                text[:2000],
                session_id=getattr(self, "_session_id", ""),
                metadata=metadata)
        except Exception as _e:
            log.debug("episodic_store_fallback", extra={"error": str(_e)[:80]})
            record = json.dumps({"text": text[:2000], "ts": time.time(),
                                  "meta": metadata or {}})
            with open(self._episodic_path, "a", encoding="utf-8", buffering=1) as f:
                f.write(record + "\n")

    def recent_episodes(self, n: int = 10) -> list[dict]:
        try:
            rows = self._get_ep_store().recent(n)
            if rows:
                return rows
        except Exception:
            pass
        if not self._episodic_path.exists():
            return []
        lines = self._episodic_path.read_text(encoding="utf-8").splitlines()
        records = []
        for line in reversed(lines[-n * 3:]):
            try:
                records.append(json.loads(line))
                if len(records) >= n:
                    break
            except Exception as _e:
                log.debug("memory_episode_parse_error", extra={"error": str(_e)[:80]})
        return list(reversed(records))

    def _load_kv(self) -> None:
        if self._kv_path.exists():
            try:
                self._kv = json.loads(self._kv_path.read_text(encoding="utf-8"))
            except Exception as _e:
                log.debug("memory_kv_load_error",
                          extra={"path": str(self._kv_path), "error": str(_e)[:120]})
                self._kv = {}

    def _save_kv(self) -> None:
        tmp = self._kv_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._kv, indent=2, default=str),
                       encoding="utf-8")
        tmp.replace(self._kv_path)

    def set(self, key: str, value: Any) -> None:
        with self._kv_lock:
            self._kv[key] = value
            self._save_kv()
        self._backend.store(f"{key}: {value}", {"key": key, "layer": "semantic"})

    def get(self, key: str, default: Any = None) -> Any:
        with self._kv_lock:
            return self._kv.get(key, default)

    def store(self, text: str, metadata: dict | None = None) -> None:
        self._backend.store(text, metadata)
        self.working_add(text, source=(metadata or {}).get("source", "store"))

    def search(self, query: str, k: int = 5) -> list[str]:
        return self._backend.search(query, k)

    def recall(self, query: str, k: int = 6) -> dict[str, list[str]]:
        def _score_texts(texts: list[str], q: str, top_k: int) -> list[str]:
            if not texts:
                return []
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                import numpy as np
                corpus = texts + [q]
                vect   = TfidfVectorizer(min_df=1, stop_words="english")
                tfidf  = vect.fit_transform(corpus)
                scores = (tfidf[:-1] @ tfidf[-1].T).toarray().ravel()
                ranked = sorted(range(len(texts)), key=lambda i: -scores[i])
                return [texts[i] for i in ranked[:top_k] if scores[i] > 0]
            except ImportError:
                q_words = set(q.lower().split())
                def _overlap(t: str) -> int:
                    return len(q_words & set(t.lower().split()))
                ranked = sorted(range(len(texts)), key=lambda i: -_overlap(texts[i]))
                return [texts[i] for i in ranked[:top_k] if _overlap(texts[i]) > 0]

        with self._working_lock:
            working_texts = [e["text"] for e in self._working]
        working_hits = _score_texts(working_texts, query, k)
        episodes      = self.recent_episodes(50)
        episodic_texts = [e["text"] for e in episodes]
        episodic_hits  = _score_texts(episodic_texts, query, k)
        semantic_hits = self.search(query, k)
        return {"working":  working_hits,
                "episodic": episodic_hits,
                "semantic": semantic_hits}

    def consolidate(self, summary: str = "") -> None:
        with self._working_lock:
            if self._working:
                combined = " | ".join(e["text"][:100] for e in self._working[-10:])
                self.record_episode(combined, {"source": "working_flush"})
                self._working.clear()
        if summary:
            self.set("last_summary", summary[:500])
            self._backend.store(summary, {"layer": "semantic", "type": "summary"})

    def facts(self) -> str:
        parts: list[str] = []
        profile = self.profile_block()
        if profile:
            parts.append(profile)
        with self._kv_lock:
            if self._kv:
                lines = ["[Memory]"]
                for k, v in list(self._kv.items())[-20:]:
                    lines.append(f"  {k}: {str(v)[:100]}")
                parts.append("\n".join(lines))
        episodes = self.recent_episodes(3)
        if episodes:
            lines = ["[Recent episodes]"]
            for ep in episodes:
                lines.append(f"  {ep['text'][:120]}")
            parts.append("\n".join(lines))
        return "\n".join(parts)

    def append_session(self, session_id: str, role: str,
                        content: str) -> None:
        path = self._sess_dir / f"{session_id}.jsonl"
        record = json.dumps({"role": role, "content": content,
                              "ts": time.time()})
        with open(path, "a", encoding="utf-8", buffering=1) as f:
            f.write(record + "\n")
        self.working_add(content[:200], source=role)

    def load_session(self, session_id: str,
                     strip_ts: bool = True) -> list[dict]:
        path = self._sess_dir / f"{session_id}.jsonl"
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if strip_ts:
                    r = {k: v for k, v in r.items() if k != "ts"}
                records.append(r)
            except Exception as _e:
                log.debug("memory_session_parse_error",
                          extra={"session": session_id, "error": str(_e)[:80]})
        return records

    def link(self, concept: str, related: str) -> None:
        key  = f"_graph:{concept.lower().strip()}"
        with self._profile_lock:
            edges: list[str] = list(self.get(key, []))
            rel = related.strip()
            if rel not in edges:
                edges.append(rel)
            self.set(key, edges)

    def related(self, concept: str, depth: int = 1) -> list[str]:
        visited: set[str] = set()
        frontier: set[str] = {concept.lower().strip()}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for node in frontier:
                key   = f"_graph:{node}"
                edges = list(self.get(key, []))
                for e in edges:
                    e_low = e.lower().strip() if isinstance(e, str) else str(e)
                    if e_low not in visited and e_low != concept.lower().strip():
                        visited.add(e_low)
                        next_frontier.add(e_low)
            frontier = next_frontier
        result: list[str] = []
        seen_low: set[str] = set()
        bfs_queue = [concept.lower().strip()]
        bfs_visited: set[str] = {concept.lower().strip()}
        for hop in range(depth):
            next_q: list[str] = []
            for node in bfs_queue:
                for raw_edge in list(self.get(f"_graph:{node}", [])):
                    raw_low = raw_edge.lower().strip() if isinstance(raw_edge, str) else str(raw_edge)
                    if raw_low not in bfs_visited and raw_low != concept.lower().strip():
                        bfs_visited.add(raw_low)
                        next_q.append(raw_low)
                        raw_str = raw_edge if isinstance(raw_edge, str) else str(raw_edge)
                        if raw_str not in seen_low:
                            seen_low.add(raw_str)
                            result.append(raw_str)
            bfs_queue = next_q
        return result

    def export_bundle(self, passphrase: str = "") -> bytes:
        import zipfile, io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            if self._episodic_path.exists():
                zf.write(self._episodic_path, "episodic.jsonl")
            if self._kv_path.exists():
                zf.write(self._kv_path, "kv.json")
            if self._profile_path.exists():
                zf.write(self._profile_path, "profile.json")
            if self._sess_dir.exists():
                for p in self._sess_dir.glob("*.jsonl"):
                    zf.write(p, f"sessions/{p.name}")
            graph_data = {k: v for k, v in self._kv.items() if k.startswith("_graph:")}
            if graph_data:
                zf.writestr("graph.json", json.dumps(graph_data, indent=2))
            manifest = {
                "version": UAIS_VERSION,
                "team_id": self._team_id,
                "exported_at": time.time(),
                "tier": self._tier,
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        raw = buf.getvalue()
        if not passphrase:
            return raw
        _BUNDLE_MAGIC = b"UAIB"
        import hashlib as _hl, secrets as _sec
        salt = _sec.token_bytes(32)
        key  = _hl.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt,
                                 SecretsVault._ITER, dklen=32)
        from uais_core.config import _AESGCM
        if _AESGCM:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM_cls
            nonce = _sec.token_bytes(12)
            ct    = _AESGCM_cls(key).encrypt(nonce, raw, None)
            encrypted = nonce + ct
        else:
            stream = b""
            block  = key
            while len(stream) < len(raw):
                block  = _hl.sha256(block).digest()
                stream += block
            encrypted = bytes(a ^ b for a, b in zip(raw, stream[:len(raw)]))
        return _BUNDLE_MAGIC + salt + encrypted

    def import_bundle(self, bundle_bytes: bytes,
                      passphrase: str = "",
                      merge: bool = False) -> dict:
        import zipfile, io
        raw = bundle_bytes
        if passphrase:
            _BUNDLE_MAGIC = b"UAIB"
            if bundle_bytes[:4] == _BUNDLE_MAGIC:
                import hashlib as _hl
                salt      = bundle_bytes[4:36]
                encrypted = bundle_bytes[36:]
                key = _hl.pbkdf2_hmac("sha256", passphrase.encode("utf-8"),
                                       salt, SecretsVault._ITER, dklen=32)
                try:
                    from uais_core.config import _AESGCM
                    if _AESGCM:
                        from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AG
                        nonce, ct = encrypted[:12], encrypted[12:]
                        raw = _AG(key).decrypt(nonce, ct, None)
                    else:
                        stream = b""
                        block  = key
                        while len(stream) < len(encrypted):
                            block  = _hl.sha256(block).digest()
                            stream += block
                        raw = bytes(a ^ b for a, b in zip(encrypted, stream[:len(encrypted)]))
                except Exception as _e:
                    raise ValueError(f"Bundle decryption failed: {_e}") from _e

        buf = io.BytesIO(raw)
        counts = {"episodic": 0, "sessions": 0, "kv_keys": 0, "graph_edges": 0}
        try:
            with zipfile.ZipFile(buf, "r") as zf:
                names = zf.namelist()
                if "episodic.jsonl" in names:
                    lines = zf.read("episodic.jsonl").decode("utf-8",
                                                              errors="replace")
                    mode = "a" if merge else "w"
                    with self._episodic_path.open(mode, encoding="utf-8") as fh:
                        fh.write(lines)
                    counts["episodic"] = lines.count("\n")
                if "kv.json" in names:
                    imported_kv = json.loads(
                        zf.read("kv.json").decode("utf-8"))
                    if merge:
                        self._kv.update(imported_kv)
                    else:
                        self._kv = imported_kv
                    self._save_kv()
                    counts["kv_keys"] = len(imported_kv)
                if "graph.json" in names:
                    graph = json.loads(zf.read("graph.json").decode("utf-8"))
                    for k, v in graph.items():
                        if merge and k in self._kv:
                            existing = list(self._kv.get(k, []))
                            for edge in (v if isinstance(v, list) else [v]):
                                if edge not in existing:
                                    existing.append(edge)
                            self._kv[k] = existing
                        else:
                            self._kv[k] = v
                        counts["graph_edges"] += len(v) if isinstance(v, list) else 1
                    self._save_kv()
                for name in names:
                    if name.startswith("sessions/") and name.endswith(".jsonl"):
                        dest = self._sess_dir / Path(name).name
                        content = zf.read(name).decode("utf-8", errors="replace")
                        mode = "a" if (merge and dest.exists()) else "w"
                        dest.write_text(content, encoding="utf-8")
                        counts["sessions"] += 1
        except zipfile.BadZipFile as e:
            raise ValueError(f"Invalid bundle format: {e}") from e
        log.info("memory_bundle_imported", extra=counts)
        return counts
