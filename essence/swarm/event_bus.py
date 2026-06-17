import asyncio
from typing import Any, Callable
from essence.core.events import log

class NeuromorphicEventBus:
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, handler: Callable):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    async def emit(self, event_type: str, data: Any):
        if event_type not in self._subscribers: return
        tasks = []
        for handler in self._subscribers[event_type]:
            try:
                if asyncio.iscoroutinefunction(handler):
                    tasks.append(asyncio.create_task(handler(data)))
                else:
                    handler(data)
            except Exception as e:
                log.debug("event_handler_error", extra={"type": event_type, "error": str(e)})
        if tasks: await asyncio.gather(*tasks, return_exceptions=True)
