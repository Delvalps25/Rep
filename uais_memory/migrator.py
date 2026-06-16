from __future__ import annotations
import json
from typing import Any
from uais_memory.vector_backends import (
    MemoryBackend, _JsonMemoryBackend, _FaissBackend, _SqliteVecBackend, _QdrantBackend
)
from uais_core.events import log

class NamespacedMemory:
    def __init__(self, base: "Memory", user_id: str) -> None:
        self._base    = base
        self._user_id = user_id
        self._prefix  = f"user:{user_id}:"

    def _k(self, key: str) -> str:
        return self._prefix + key

    def set(self, key: str, value: Any) -> None:
        self._base.set(self._k(key), value)

    def get(self, key: str, default: Any = None) -> Any:
        return self._base.get(self._k(key), default)

    def store(self, text: str, metadata: dict | None = None) -> None:
        meta = dict(metadata or {})
        meta["user_id"] = self._user_id
        self._base.store(text, meta)

    def recall(self, query: str, k: int = 5) -> dict:
        return self._base.recall(query, k=k)

    def append_session(self, session_id: str, role: str, content: str) -> None:
        self._base.append_session(
            f"{self._user_id}_{session_id}", role, content)

    def load_session(self, session_id: str) -> list[dict]:
        return self._base.load_session(f"{self._user_id}_{session_id}")

    def working_add(self, text: str, source: str = "") -> None:
        self._base.working_add(text, source)

    def working_context(self, n: int) -> list[str]:
        return self._base.working_context(n)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

class MemoryMigrator:
    @staticmethod
    def _extract(source: MemoryBackend) -> list[tuple[str, dict]]:
        records: list[tuple[str, dict]] = []
        if isinstance(source, _JsonMemoryBackend):
            records = [(e['text'], e.get('meta', {}))
                       for e in source._entries]
        elif isinstance(source, _FaissBackend) and source._ready:
            records = [(t, {}) for t in source._texts]
        elif isinstance(source, _SqliteVecBackend) and source._ready:
            try:
                rows = source._con.execute(
                    'SELECT text FROM mem').fetchall()
                records = [(r[0], {}) for r in rows]
            except Exception as _e:
                log.debug("memory_migrate_sqlite_read_error", extra={"error": str(_e)[:120]})
        elif isinstance(source, _QdrantBackend) and source._ready:
            try:
                scroll_result = source._client.scroll(
                    collection_name=source.COLLECTION,
                    limit=10_000,
                    with_payload=True,
                )
                for point in scroll_result[0]:
                    text = point.payload.get('text', '')
                    meta = {k: v for k, v in point.payload.items()
                            if k != 'text'}
                    if text:
                        records.append((text, meta))
            except Exception as _e:
                log.debug("memory_migrate_qdrant_read_error", extra={"error": str(_e)[:120]})
        return records

    @staticmethod
    def migrate(source: MemoryBackend,
                dest:   MemoryBackend) -> int:
        records = MemoryMigrator._extract(source)
        count   = 0
        for text, meta in records:
            try:
                dest.store(text, meta)
                count += 1
            except Exception as exc:
                log.warning('migrator_store_failed',
                            extra={'error': str(exc), 'text_snippet': text[:60]})
        log.info('memory_migrated', extra={
            'source': type(source).__name__,
            'dest':   type(dest).__name__,
            'count':  count,
        })
        return count

    @staticmethod
    def export_jsonl(source: MemoryBackend, path: Path) -> int:
        records = MemoryMigrator._extract(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            for text, meta in records:
                fh.write(json.dumps({'text': text, 'meta': meta}) + '\n')
        log.info('memory_exported_jsonl',
                 extra={'path': str(path), 'count': len(records)})
        return len(records)

    @staticmethod
    def import_jsonl(path: Path, dest: MemoryBackend) -> int:
        count = 0
        with open(path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec  = json.loads(line)
                    dest.store(rec.get('text', ''),
                               rec.get('meta', {}))
                    count += 1
                except Exception as exc:
                    log.warning('migrator_import_failed',
                                extra={'error': str(exc)})
        log.info('memory_imported_jsonl',
                 extra={'path': str(path), 'count': count})
        return count
