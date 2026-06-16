import json
import secrets
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

class ChannelAdapter:
    """Base class. Implement send() and poll() for each platform."""
    NAME = "base"

    def send(self, text: str, target: str) -> None:
        pass

    def poll(self) -> List[Dict[str, Any]]:
        """Return list of {"from": str, "text": str, "ts": float, "channel": str}."""
        return []

    def available(self) -> bool:
        return False

class ChannelIdentity:
    """Cross-channel identity registry."""

    def __init__(self, workspace: Path) -> None:
        self._path = workspace / "channel_identity.json"
        self._map: Dict[str, str] = {}   # "channel:external_id" → user_id
        self._lock = threading.Lock()
        if self._path.exists():
            try:
                self._map = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._map = {}

    def _key(self, channel: str, external_id: str) -> str:
        return f"{channel}:{external_id}"

    def resolve(self, channel: str, external_id: str) -> str:
        k = self._key(channel, external_id)
        with self._lock:
            if k not in self._map:
                self._map[k] = f"uid_{secrets.token_hex(6)}"
                self._save()
            return self._map[k]

    def link(self, channel: str, external_id: str, user_id: str) -> None:
        k = self._key(channel, external_id)
        with self._lock:
            self._map[k] = user_id
            self._save()

    def lookup(self, channel: str, external_id: str) -> Optional[str]:
        return self._map.get(self._key(channel, external_id))

    def _save(self) -> None:
        try:
            self._path.write_text(json.dumps(self._map, indent=2), encoding="utf-8")
        except Exception:
            pass

class TelegramAdapter(ChannelAdapter):
    NAME = "telegram"
    def available(self) -> bool:
        return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))

class DiscordAdapter(ChannelAdapter):
    NAME = "discord"
    def available(self) -> bool:
        return bool(os.environ.get("DISCORD_BOT_TOKEN"))

import os
