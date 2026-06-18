import threading
from pathlib import Path
from typing import Any, List, Dict, Optional
from essence.config import log

try:
    import duckdb as _duckdb
    _DUCKDB = True
except ImportError:
    _DUCKDB = False

class DuckDBAnalytics:
    def __init__(self, workspace: Path) -> None:
        self._ws = workspace
        self._conn = None

    def _ensure_conn(self) -> Any:
        if not _DUCKDB: return None
        if self._conn is None:
            self._conn = _duckdb.connect(":memory:")
        return self._conn

    def query(self, sql: str) -> List[Dict]:
        conn = self._ensure_conn()
        if not conn: return []
        try:
            return conn.execute(sql).fetchdf().to_dict("records")
        except Exception as e:
            log.debug("duckdb_query_error", extra={"error": str(e)})
            return []
