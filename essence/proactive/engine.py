import os
import json
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any

@dataclass
class ProactiveEvent:
    kind:       str     # "stale_project" | "disk_alert" | "memory_gap" | "deadline"
    title:      str
    body:       str
    priority:   int     # 0 (info) → 4 (critical)
    action_hint: str    = ""
    created_at: float   = 0.0

    def format(self) -> str:
        icons = {0: "ℹ", 1: "·", 2: "⚠", 3: "⚡", 4: "🚨"}
        icon = icons.get(self.priority, "·")
        lines = [f"{icon} **{self.title}**", f"  {self.body}"]
        if self.action_hint:
            lines.append(f"  → {self.action_hint}")
        return "\n".join(lines)

class ProactiveEngine:
    """
    Scans environment and memory for events worth surfacing proactively.
    """

    STALE_DAYS      = 7
    DISK_WARN_PCT   = 80
    DISK_CRIT_PCT   = 90

    def __init__(self, workspace: Path, memory: Any,
                 event_bus: Any = None) -> None:
        self._ws   = workspace
        self._mem  = memory
        self._bus  = event_bus
        # Subscribe to webhook events for event-driven proactivity
        if event_bus:
            event_bus.subscribe("github.push", self._on_github_push)
            event_bus.subscribe("gcal.event_upcoming", self._on_gcal_event)
            event_bus.subscribe("gmail.message", self._on_gmail_message)

    def _on_github_push(self, event: Any) -> None:
        """Handle a GitHub push event."""
        self._mem.set(
            f"_proactive_pending_{int(time.time())}",
            json.dumps({"kind": "github_push",
                        "title": "New code push",
                        "body": event.summary() if hasattr(event, 'summary') else str(event),
                        "priority": 1,
                        "action_hint": "Review and summarise the changes?"}))

    def _on_gcal_event(self, event: Any) -> None:
        """Handle an upcoming calendar event."""
        self._mem.set(
            f"_proactive_pending_{int(time.time())}",
            json.dumps({"kind": "calendar_reminder",
                        "title": "Upcoming calendar event",
                        "body": event.summary() if hasattr(event, 'summary') else str(event),
                        "priority": 2,
                        "action_hint": "Prepare a briefing?"}))

    def _on_gmail_message(self, event: Any) -> None:
        """Handle a Gmail message."""
        pass

    def scan(self) -> list[ProactiveEvent]:
        """Perform manual scans for stale projects, disk usage, etc."""
        events = []
        # Disk check
        try:
            import shutil
            usage = shutil.disk_usage(self._ws)
            pct = (usage.used / usage.total) * 100
            if pct > self.DISK_CRIT_PCT:
                events.append(ProactiveEvent("disk_alert", "Disk Critical", f"Workspace at {pct:.1f}% capacity", 4, "Clean up temporary files?"))
            elif pct > self.DISK_WARN_PCT:
                events.append(ProactiveEvent("disk_alert", "Disk Warning", f"Workspace at {pct:.1f}% capacity", 2))
        except Exception:
            pass

        return events
