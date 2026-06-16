from __future__ import annotations
import hashlib
import json
import secrets
import time
from pathlib import Path
from typing import Any
from uais_core.events import log
from uais_core.infra.fast_json import _fast_loads, _fast_dumps

_EPISODIC_DDL = """
    CREATE TABLE IF NOT EXISTS episodes (
        id         TEXT PRIMARY KEY,
        ts         REAL    NOT NULL,
        session_id TEXT    DEFAULT '',
        text       TEXT    NOT NULL,
        meta_json  TEXT    DEFAULT '{}',
        prism_type TEXT    DEFAULT 'episode' -- episode | spectrum_report
    );
    CREATE INDEX IF NOT EXISTS idx_episodes_ts ON episodes(ts DESC);
"""

_EPISODIC_FTS_DDL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
    USING fts5(text, content=episodes, content_rowid=rowid);

    CREATE TRIGGER IF NOT EXISTS episodes_ai
    AFTER INSERT ON episodes BEGIN
        INSERT INTO episodes_fts(rowid, text) VALUES (new.rowid, new.text);
    END;

    CREATE TRIGGER IF NOT EXISTS episodes_ad
    AFTER DELETE ON episodes BEGIN
        INSERT INTO episodes_fts(episodes_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
    END;

    CREATE TRIGGER IF NOT EXISTS episodes_au
    AFTER UPDATE ON episodes BEGIN
        INSERT INTO episodes_fts(episodes_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
        INSERT INTO episodes_fts(rowid, text) VALUES (new.rowid, new.text);
    END;
"""

def _episodic_add_fts(store: "EpisodicStore") -> None:
    try:
        with store._conn() as conn:
            conn.executescript(_EPISODIC_FTS_DDL)
            conn.execute(
                "INSERT INTO episodes_fts(rowid, text) "
                "SELECT rowid, text FROM episodes "
                "WHERE rowid NOT IN (SELECT rowid FROM episodes_fts)")
    except Exception as _e:
        log.debug("episodic_fts_setup_error", extra={"error": str(_e)[:80]})


def episodic_search(store: "EpisodicStore",
                     query: str, n: int = 10) -> list[dict]:
    try:
        import sqlite3 as _sq3
        with store._conn() as conn:
            tables = {r[0] for r in
                      conn.execute("SELECT name FROM sqlite_master "
                                   "WHERE type='table'").fetchall()}
            if "episodes_fts" not in tables:
                _episodic_add_fts(store)
            rows = conn.execute(
                "SELECT e.id, e.ts, e.session_id, e.text, e.meta_json, "
                "       bm25(episodes_fts) rank "
                "FROM episodes e "
                "JOIN episodes_fts f ON e.rowid = f.rowid "
                "WHERE episodes_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (query, n)).fetchall()
        return [{"id": r[0], "ts": r[1], "session_id": r[2],
                 "text": r[3], "meta": _fast_loads(r[4]),
                 "rank": r[5]}
                for r in rows]
    except Exception as _e:
        log.debug("episodic_fts_search_error", extra={"error": str(_e)[:80]})
        return store.recent(n)

class EpisodicStore:
    def __init__(self, workspace: Path) -> None:
        self._db_path = workspace / "memory" / "episodic.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        _episodic_add_fts(self)
        self._migrate_jsonl(workspace / "memory" / "episodic.jsonl")

    def _conn(self) -> Any:
        import sqlite3 as _sq3
        conn = _sq3.connect(str(self._db_path), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_EPISODIC_DDL)

    def _migrate_jsonl(self, jsonl_path: Path) -> None:
        if not jsonl_path.exists():
            return
        migrated = 0
        try:
            import sqlite3 as _sq3
            with self._conn() as conn:
                existing = {r[0] for r in
                            conn.execute("SELECT id FROM episodes").fetchall()}
                with open(jsonl_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            ep = _fast_loads(line)
                            eid = ep.get("id") or hashlib.sha256(
                                line.encode()).hexdigest()[:16]
                            if eid in existing:
                                continue
                            conn.execute(
                                "INSERT OR IGNORE INTO episodes "
                                "(id, ts, session_id, text, meta_json) VALUES (?,?,?,?,?)",
                                (eid,
                                 float(ep.get("ts", 0)),
                                 str(ep.get("session_id", "")),
                                 str(ep.get("text", "")),
                                 _fast_dumps(ep.get("meta", {}))))
                            migrated += 1
                        except Exception:
                            pass
            if migrated > 0:
                log.info("episodic_jsonl_migrated",
                         extra={"count": migrated,
                                "source": str(jsonl_path)})
        except Exception as _e:
            log.debug("episodic_migration_error",
                      extra={"error": str(_e)[:80]})

    def record(self, text: str, session_id: str = "",
                metadata: dict | None = None, prism_type: str = "episode") -> str:
        eid  = secrets.token_hex(8)
        now  = time.time()
        meta = _fast_dumps(metadata or {})
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO episodes (id, ts, session_id, text, meta_json, prism_type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (eid, now, session_id, text[:8000], meta, prism_type))
        return eid

    def recent(self, n: int = 20, session_id: str = "") -> list[dict]:
        with self._conn() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT id, ts, session_id, text, meta_json "
                    "FROM episodes WHERE session_id=? "
                    "ORDER BY ts DESC LIMIT ?",
                    (session_id, n)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, ts, session_id, text, meta_json "
                    "FROM episodes ORDER BY ts DESC LIMIT ?",
                    (n,)).fetchall()
        return [{"id": r[0], "ts": r[1], "session_id": r[2],
                 "text": r[3], "meta": _fast_loads(r[4])}
                for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]

    def search(self, query: str, n: int = 10) -> list[dict]:
        return episodic_search(self, query, n)

    def prune_before(self, cutoff_ts: float) -> int:
        with self._conn() as conn:
            cursor = conn.execute(
                "DELETE FROM episodes WHERE ts < ?", (cutoff_ts,))
            return cursor.rowcount
