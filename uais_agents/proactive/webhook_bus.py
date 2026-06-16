from __future__ import annotations
import json
import time
import threading
import dataclasses as _dc
from pathlib import Path
from typing import Any, Callable, list
from collections import defaultdict as _defaultdict
from uais_core.events import log

@_dc.dataclass
class WebhookEvent:
    source:    str
    event_type: str
    payload:   dict
    received_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.received_at:
            self.received_at = time.time()

    @property
    def key(self) -> str:
        return f"{self.source}.{self.event_type}"

    def summary(self) -> str:
        parts = []
        p = self.payload
        if self.source == "github":
            repo = p.get("repository", {}).get("full_name", "")
            if self.event_type == "push":
                branch = p.get("ref", "").replace("refs/heads/", "")
                n_commits = len(p.get("commits", []))
                parts.append(f"Push to {repo}/{branch}: {n_commits} commit(s)")
            elif "pull_request" in p:
                pr = p["pull_request"]
                parts.append(f"PR #{pr.get('number')} '{pr.get('title','')}' [{self.event_type}] on {repo}")
        elif self.source == "gcal":
            summary = p.get("summary", p.get("title", "event"))
            start   = p.get("start", {}).get("dateTime", p.get("start", {}).get("date", ""))
            parts.append(f"Calendar: '{summary}' at {start}")
        elif self.source == "gmail":
            subject = p.get("subject", "")
            sender  = p.get("from", "")
            parts.append(f"Email from {sender}: '{subject}'")
        else:
            parts.append(f"{self.source}/{self.event_type}: {json.dumps(p)[:120]}")
        return " | ".join(parts) if parts else f"{self.key}"

class WebhookEventBus:
    def __init__(self, workspace: Path, memory: Any) -> None:
        self._ws         = workspace
        self._mem        = memory
        self._handlers:  dict[str, list] = _defaultdict(list)
        self._lock       = threading.Lock()
        self._event_log  = workspace / "logs" / "webhook_events.jsonl"
        self._event_log.parent.mkdir(parents=True, exist_ok=True)

    def subscribe(self, event_key: str,
                  handler: Callable[[WebhookEvent], None]) -> None:
        with self._lock:
            self._handlers[event_key].append(handler)
            log.debug("webhook_subscribed", extra={"key": event_key})

    def unsubscribe_all(self, event_key: str) -> None:
        with self._lock:
            self._handlers.pop(event_key, None)

    def publish(self, event: WebhookEvent) -> None:
        try:
            with open(self._event_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": event.received_at, "key": event.key,
                    "summary": event.summary()}) + "\n")
        except Exception: pass

        with self._lock:
            handlers = (list(self._handlers.get(event.key, [])) +
                        list(self._handlers.get("*", [])))

        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                log.error("webhook_handler_error",
                          extra={"key": event.key, "error": str(e)[:120]})
