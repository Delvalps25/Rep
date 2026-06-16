import math
import json
import hashlib
import struct
import os
import threading
import urllib.request
from pathlib import Path
from typing import Any
from uais_core.events import log
from uais_core.config import OLLAMA_HOST

class MemoryBackend:
    """Abstract base for pluggable vector memory backends."""
    def store(self, text: str, metadata: dict | None = None) -> None:
        pass
    def search(self, query: str, k: int = 5) -> list[str]:
        return []

def _bm25_search(entries: list[str], query: str, k: int) -> list[str]:
    import math
    query_terms = query.lower().split()
    if not query_terms or not entries:
        return []
    N = len(entries)
    df: dict[str, int] = {}
    for term in query_terms:
        df[term] = sum(1 for e in entries if term in e.lower())
    scored: list[tuple[float, str]] = []
    for text in entries:
        tl = text.lower()
        doc_len = max(len(tl.split()), 1)
        score = sum(
            (tl.count(t) / doc_len) * (math.log((N + 1) / (df.get(t, 0) + 1)) + 1.0)
            for t in query_terms
        )
        if score > 0:
            scored.append((score, text))
    scored.sort(reverse=True)
    return [t for _, t in scored[:k]]

def _rrf_merge(vec_results: list[str], bm25_results: list[str],
               k: int, rrf_k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for rank, text in enumerate(vec_results, start=1):
        scores[text] = scores.get(text, 0.0) + 1.0 / (rrf_k + rank)
    for rank, text in enumerate(bm25_results, start=1):
        scores[text] = scores.get(text, 0.0) + 1.0 / (rrf_k + rank)
    return [t for t, _ in sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]]

class _JsonMemoryBackend(MemoryBackend):
    def __init__(self, path: Path):
        self._path = path
        self._entries: list[dict] = []
        if path.exists():
            try: self._entries = json.loads(path.read_text(encoding="utf-8"))
            except Exception: self._entries = []

    def store(self, text: str, metadata: dict | None = None) -> None:
        self._entries.append({"text": text, "meta": metadata or {}})
        self._path.write_text(json.dumps(self._entries[-500:], indent=2), encoding="utf-8")

    def search(self, query: str, k: int = 5) -> list[str]:
        return _bm25_search([e["text"] for e in self._entries], query, k)

class _SqliteVecBackend(MemoryBackend):
    def __init__(self, path: Path):
        self._db_path = str(path / "memory.db")
        self._ready   = False
        try:
            import sqlite_vec
            import sqlite3
            self._con = sqlite3.connect(self._db_path)
            self._con.enable_load_extension(True)
            sqlite_vec.load(self._con)
            self._con.execute("CREATE TABLE IF NOT EXISTS mem(embedding BLOB, text TEXT)")
            self._ready = True
        except Exception:
            self._ready = False

    def _embed(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode()).digest()
        raw = (h * (384 * 4 // len(h) + 1))[:384 * 4]
        vals = [struct.unpack("f", raw[i:i+4])[0] for i in range(0, len(raw), 4)]
        mag = math.sqrt(sum(v*v for v in vals)) or 1.0
        return [v / mag for v in vals]

    def store(self, text: str, metadata: dict | None = None) -> None:
        if not self._ready: return
        import json as _json
        emb = self._embed(text)
        self._con.execute(
            "INSERT INTO mem(embedding, text) VALUES (?, ?)",
            (_json.dumps(emb), text))
        self._con.commit()

    def search(self, query: str, k: int = 5) -> list[str]:
        if not self._ready:
            rows = self._con.execute("SELECT text FROM mem").fetchall() if hasattr(self, "_con") else []
            return _bm25_search([r[0] for r in rows], query, k)
        import json as _json
        emb = _json.dumps(self._embed(query))
        vec_rows = self._con.execute(
            "SELECT text FROM mem ORDER BY vec_distance_cosine(embedding, ?) LIMIT ?",
            (emb, k * 2)).fetchall()
        all_rows = self._con.execute("SELECT text FROM mem").fetchall()
        vec_results  = [r[0] for r in vec_rows]
        bm25_results = _bm25_search([r[0] for r in all_rows], query, k * 2)
        return _rrf_merge(vec_results, bm25_results, k)

class _FaissBackend(MemoryBackend):
    def __init__(self, path: Path):
        self._path  = path
        self._ready = False
        self._texts: list[str] = []
        self._embed_mode: str = "hash"
        try:
            import faiss
            import numpy as np
            self._faiss = faiss
            self._np    = np
            self._dim   = 384
            self._index = faiss.IndexFlatL2(self._dim)
            idx_file  = path / "faiss.index"
            txt_file  = path / "faiss_texts.json"
            meta_file = path / "faiss_meta.json"
            if idx_file.exists() and txt_file.exists():
                self._index = faiss.read_index(str(idx_file))
                self._texts = json.loads(txt_file.read_text(encoding="utf-8"))
                if meta_file.exists():
                    self._embed_mode = json.loads(
                        meta_file.read_text(encoding="utf-8")).get("embed_mode", "hash")
            self._dirty = False
            self._ready = True
        except Exception:
            self._ready = False

    def _embed(self, text: str) -> "Any":
        can_semantic = False
        try:
            from sentence_transformers import SentenceTransformer
            can_semantic = True
        except ImportError:
            pass

        if self._texts and self._embed_mode == "hash" and can_semantic:
            can_semantic = False
        elif self._texts and self._embed_mode == "semantic" and not can_semantic:
            import warnings
            warnings.warn("sentence-transformers not installed", RuntimeWarning)

        if can_semantic:
            if not hasattr(self, "_st_model"):
                from sentence_transformers import SentenceTransformer
                self._st_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            self._embed_mode = "semantic"
            vec = self._st_model.encode([text], normalize_embeddings=True)
            return self._np.array(vec, dtype="float32")

        self._embed_mode = "hash"
        import hashlib, struct
        h = hashlib.sha256(text.encode()).digest()
        raw = (h * (self._dim * 4 // len(h) + 1))[:self._dim * 4]
        vec_vals = [struct.unpack("f", raw[i:i+4])[0] for i in range(0, len(raw), 4)]
        return self._np.array([vec_vals[:self._dim]], dtype="float32")

    def store(self, text: str, metadata: dict | None = None) -> None:
        if not self._ready: return
        self._index.add(self._embed(text))
        self._texts.append(text)
        self._dirty = True

    def search(self, query: str, k: int = 5) -> list[str]:
        if not self._ready or not self._texts: return []
        fetch = min(k * 2, len(self._texts))
        _, idx = self._index.search(self._embed(query), fetch)
        vec_results  = [self._texts[i] for i in idx[0] if 0 <= i < len(self._texts)]
        bm25_results = _bm25_search(self._texts, query, fetch)
        return _rrf_merge(vec_results, bm25_results, k)

class _QdrantBackend(MemoryBackend):
    COLLECTION = "uais_memory"
    def __init__(self):
        self._ready = False
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
            self._client = QdrantClient(host="localhost", port=6333)
            _existing = [c.name for c in self._client.get_collections().collections]
            if self.COLLECTION not in _existing:
                self._client.create_collection(
                    collection_name=self.COLLECTION,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE))
            self._dim   = 384
            self._ready = True
        except Exception:
            self._ready = False

    def _embed(self, text: str) -> list[float]:
        try:
            from sentence_transformers import SentenceTransformer
            if not hasattr(self, "_st_model"):
                self._st_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
            vec = self._st_model.encode([text], normalize_embeddings=True)
            return vec[0].tolist()
        except ImportError: pass
        import hashlib, struct
        h = hashlib.sha256(text.encode()).digest()
        raw = (h * (self._dim * 4 // len(h) + 1))[:self._dim * 4]
        return [struct.unpack("f", raw[i:i+4])[0] for i in range(0, len(raw), 4)]

    def store(self, text: str, metadata: dict | None = None) -> None:
        if not self._ready: return
        from qdrant_client.models import PointStruct
        import uuid
        self._client.upsert(
            collection_name=self.COLLECTION,
            points=[PointStruct(id=str(uuid.uuid4()), vector=self._embed(text),
                                payload={"text": text, **(metadata or {})})])

    def search(self, query: str, k: int = 5) -> list[str]:
        if not self._ready: return []
        hits = self._client.search(collection_name=self.COLLECTION, query_vector=self._embed(query), limit=k*2)
        vec_results = [h.payload.get("text", "") for h in hits if h.payload]
        return vec_results

class _ChromaMemoryBackend(MemoryBackend):
    EMBED_MODEL = os.environ.get("UAIS_EMBED_MODEL", "nomic-embed-text")
    def __init__(self, persist_dir: Path) -> None:
        self._dir   = persist_dir
        self._col   = None
        self._init()

    def _init(self) -> None:
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=str(self._dir))
            self._col    = self._client.get_or_create_collection("uais_semantic")
        except Exception: pass

    def store(self, text: str, metadata: dict) -> None:
        if self._col:
            doc_id = hashlib.sha256(text.encode()).hexdigest()[:16]
            self._col.upsert(ids=[doc_id], documents=[text], metadatas=[metadata or {}])

    def search(self, query: str, k: int = 5) -> list[str]:
        if self._col:
            res = self._col.query(query_texts=[query], n_results=k)
            return res.get("documents", [[]])[0]
        return []

def _make_memory_backend(path: Path, tier: int) -> MemoryBackend:
    if tier >= 3: return _QdrantBackend()
    if tier >= 1: return _FaissBackend(path)
    return _SqliteVecBackend(path)
