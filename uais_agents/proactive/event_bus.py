import time
import json
import threading
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from collections import defaultdict as _defaultdict
from uais_core.events import log

class WebhookEvent:
    """A single event received from an external source."""
    def __init__(self, source: str, event_type: str, payload: Dict, received_at: float = 0.0):
        self.source = source
        self.event_type = event_type
        self.payload = payload
        self.received_at = received_at or time.time()

    @property
    def key(self) -> str:
        return f"{self.source}.{self.event_type}"

    def summary(self) -> str:
        """Human-readable one-liner for logging and ProactiveEvent body."""
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
    """
    Lightweight in-process event bus for webhook-driven triggers.
    """

    def __init__(self, workspace: Path, memory: Any) -> None:
        self._ws         = workspace
        self._mem        = memory
        self._handlers:  Dict[str, List[Callable]] = _defaultdict(list)
        self._queue:     Optional[asyncio.Queue] = None
        self._thread:    Optional[threading.Thread] = None
        self._running    = False
        self._lock       = threading.Lock()
        self._event_log  = workspace / "logs" / "webhook_events.jsonl"
        self._event_log.parent.mkdir(parents=True, exist_ok=True)

    def subscribe(self, event_key: str, handler: Callable[[WebhookEvent], None]) -> None:
        with self._lock:
            self._handlers[event_key].append(handler)
            log.debug("webhook_subscribed", extra={"key": event_key})

    def publish(self, event: WebhookEvent) -> None:
        try:
            with open(self._event_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": event.received_at, "key": event.key,
                    "summary": event.summary()}) + "\n")
        except Exception:
            pass

        with self._lock:
            handlers = self._handlers.get(event.key, []) + self._handlers.get("*", [])
            for h in handlers:
                try:
                    h(event)
                except Exception as e:
                    log.error("webhook_handler_error", extra={"key": event.key, "error": str(e)})
