import time
import threading
from typing import Any

class MessageProtocol:
    def __init__(self, version: str = "1.0"):
        self.version = version
    def wrap(self, sender: str, receiver: str,
             msg_type: str, content: Any) -> dict:
        return {
            "v":       self.version,
            "ts":      time.time(),
            "from":    sender,
            "to":      receiver,
            "type":    msg_type,
            "payload": content
        }
    def validate(self, msg: dict) -> bool:
        required = {"v", "ts", "from", "to", "type", "payload"}
        return all(k in msg for k in required)

class TaskHandoff:
    def __init__(self):
        self._locks: dict[str, str] = {}
        self._lock = threading.Lock()
    def claim(self, task_id: str, agent_id: str) -> bool:
        with self._lock:
            if task_id in self._locks: return False
            self._locks[task_id] = agent_id
            return True
    def release(self, task_id: str, agent_id: str):
        with self._lock:
            if self._locks.get(task_id) == agent_id:
                del self._locks[task_id]
    def transfer(self, task_id: str, from_agent: str, to_agent: str) -> bool:
        with self._lock:
            if self._locks.get(task_id) != from_agent: return False
            self._locks[task_id] = to_agent
            return True

class ConflictResolution:
    def resolve_by_voting(self, options: dict[str, int]) -> str:
        if not options: return ""
        return max(options, key=options.get)
    def arbitrate(self, proposal_a: str, proposal_b: str,
                  priority_a: int, priority_b: int) -> str:
        if priority_a >= priority_b:
            return proposal_a
        return proposal_b
