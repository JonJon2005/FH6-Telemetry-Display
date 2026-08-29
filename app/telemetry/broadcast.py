"""Latest-value broadcast fan-out for realtime WebSocket clients."""

from __future__ import annotations

import asyncio


class LatestValueBroadcaster:
    """Fan out snapshots without ever applying backpressure to UDP reception."""

    def __init__(self, maximum_clients: int) -> None:
        self.maximum_clients = maximum_clients
        self._subscribers: set[asyncio.Queue[dict[str, object]]] = set()
        self.latest: dict[str, object] | None = None
        self.published_count = 0
        self.dropped_updates = 0

    @property
    def active_clients(self) -> int:
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[dict[str, object]] | None:
        if len(self._subscribers) >= self.maximum_clients:
            return None
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=1)
        self._subscribers.add(queue)
        if self.latest is not None:
            # New screens get the latest reading right away.
            queue.put_nowait(self.latest)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, value: dict[str, object]) -> None:
        self.latest = value
        self.published_count += 1
        for queue in tuple(self._subscribers):
            if queue.full():
                # A slow screen only needs the newest update.
                try:
                    queue.get_nowait()
                    self.dropped_updates += 1
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(value)
