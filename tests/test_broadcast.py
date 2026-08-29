from __future__ import annotations

import asyncio

from app.telemetry.broadcast import LatestValueBroadcaster


def test_slow_subscriber_keeps_only_latest_value() -> None:
    async def scenario() -> None:
        broadcaster = LatestValueBroadcaster(maximum_clients=2)
        queue = broadcaster.subscribe()
        assert queue is not None
        broadcaster.publish({"sequence": 1})
        broadcaster.publish({"sequence": 2})
        broadcaster.publish({"sequence": 3})
        assert queue.qsize() == 1
        assert await queue.get() == {"sequence": 3}
        assert broadcaster.dropped_updates == 2
        broadcaster.unsubscribe(queue)
        assert broadcaster.active_clients == 0

    asyncio.run(scenario())


def test_client_limit_is_enforced() -> None:
    broadcaster = LatestValueBroadcaster(maximum_clients=1)
    first = broadcaster.subscribe()
    assert first is not None
    assert broadcaster.subscribe() is None
    broadcaster.unsubscribe(first)
    assert broadcaster.subscribe() is not None
