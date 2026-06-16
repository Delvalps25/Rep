from __future__ import annotations
import os
import threading
import time
import json
import urllib.request
import urllib.parse
from typing import Any, List as list
from uais_core.events import log
from uais_memory.semantic_state import SemanticStateStore, SemanticFact
from uais_core.connection_pool import http_get_json

_TEAM_SYNC_ENABLED  = os.environ.get("UAIS_TEAM_SYNC", "0") == "1"
_TEAM_SYNC_INTERVAL = int(os.environ.get("UAIS_TEAM_SYNC_INTERVAL", "300"))

class TeamMemorySync:
    def __init__(self, store: SemanticStateStore,
                 peer_urls: list[str],
                 namespace: str = "local") -> None:
        self._store     = store
        self._peers     = peer_urls
        self._namespace = namespace
        self._last_push = 0.0
        self._pending:  list[dict] = []
        self._stop      = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not _TEAM_SYNC_ENABLED or not self._peers:
            return
        if self._namespace == "local":
            log.debug("team_sync_skipped", extra={"reason": "namespace=local"})
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="uais-team-sync")
        self._thread.start()
        log.info("team_sync_started", extra={"peers": len(self._peers),
                                              "interval": _TEAM_SYNC_INTERVAL})

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(timeout=_TEAM_SYNC_INTERVAL):
            try:
                self._sync_cycle()
            except Exception as _e:
                log.warning("team_sync_error", extra={"error": str(_e)[:200]})

    def _sync_cycle(self) -> None:
        since = self._last_push
        new_facts = [
            f.to_dict() for f in self._store.query()
            if f.ts > since and f.source != "private"
        ]
        to_push = self._pending + new_facts
        if to_push:
            delivered = self._push(to_push)
            self._pending = [] if delivered else to_push
        for peer_url in self._peers:
            pulled = self._pull_from(peer_url, since)
            for fd in pulled:
                try:
                    f = SemanticFact.from_dict(fd)
                    if f.source == "private": continue
                    self._store.assert_fact(
                        f.entity, f.relation, f.attribute,
                        f.value, f.confidence, source="team_sync")
                except Exception:
                    pass
        self._last_push = time.time()
        log.debug("team_sync_cycle_done",
                  extra={"pushed": len(to_push), "pending": len(self._pending),
                         "peers": len(self._peers)})

    def _push(self, facts: list[dict]) -> bool:
        payload = json.dumps({"namespace": self._namespace, "facts": facts}).encode()
        all_ok = True
        for peer_url in self._peers:
            try:
                req = urllib.request.Request(
                    f"{peer_url.rstrip('/')}/a2a/team-memory/push",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST")
                urllib.request.urlopen(req, timeout=10)
            except Exception as _e:
                log.debug("team_sync_push_error",
                           extra={"peer": peer_url, "error": str(_e)[:80]})
                all_ok = False
        return all_ok

    def _pull_from(self, peer_url: str, since: float) -> list[dict]:
        try:
            url = (f"{peer_url.rstrip('/')}/a2a/team-memory/pull"
                   f"?namespace={urllib.parse.quote(self._namespace)}&since={since}")
            return http_get_json(url, timeout=10).get("facts", [])
        except Exception:
            return []
