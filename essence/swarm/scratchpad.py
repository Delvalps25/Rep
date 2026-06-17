import time

class ReasoningScratchpad:
    def __init__(self, max_entries: int = 50):
        self._entries: list[dict] = []; self._max = max_entries
    def note(self, thought: str, kind: str = "reasoning", step_id: int = 0) -> None:
        self._entries.append({"thought": thought[:500], "kind": kind, "step_id": step_id, "ts": time.time()})
        if len(self._entries) > self._max * 2: self._entries = self._entries[-self._max:]
    def review(self, last_n: int = 10) -> list[dict]: return self._entries[-last_n:]
    def to_context(self, last_n: int = 5) -> str:
        entries = self.review(last_n)
        if not entries: return ""
        lines = ["[Reasoning Scratchpad]"]
        for e in entries: lines.append(f"  [{e['kind']}] {e['thought']}")
        return "\n".join(lines)
    def clear(self) -> None: self._entries.clear()
