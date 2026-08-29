"""Lifecycle for Windows-safe UDP reception and normalized broadcasting."""

from __future__ import annotations

import asyncio
import socket
from typing import TYPE_CHECKING

from app.config import Settings
from .broadcast import LatestValueBroadcaster
from .receiver import TelemetryUDPProtocol
from .state import TelemetryState

if TYPE_CHECKING:
    from app.sessions.recorder import SessionRecorder


class LiveTelemetryService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state = TelemetryState(settings)
        self.broadcaster = LatestValueBroadcaster(settings.max_websocket_clients)
        self.debug_clients = 0
        self._transport: asyncio.DatagramTransport | None = None
        self._publisher_task: asyncio.Task[None] | None = None
        self.recorder: SessionRecorder | None = None

    @property
    def running(self) -> bool:
        return self._publisher_task is not None and not self._publisher_task.done()

    @property
    def websocket_clients(self) -> int:
        return self.broadcaster.active_clients + self.debug_clients

    def subscribe_realtime(self) -> asyncio.Queue[dict[str, object]] | None:
        if self.websocket_clients >= self.settings.max_websocket_clients:
            return None
        return self.broadcaster.subscribe()

    def add_debug_client(self) -> bool:
        if self.websocket_clients >= self.settings.max_websocket_clients:
            return False
        self.debug_clients += 1
        return True

    def remove_debug_client(self) -> None:
        self.debug_clients = max(0, self.debug_clients - 1)

    async def start(self) -> None:
        if self.running:
            return
        if self.recorder is not None:
            self.recorder.start()
        try:
            loop = asyncio.get_running_loop()
            transport, _ = await loop.create_datagram_endpoint(
                lambda: TelemetryUDPProtocol(self.state),
                local_addr=(self.settings.udp_host, self.settings.udp_port),
                family=socket.AF_INET,
            )
            self._transport = transport
        except OSError as error:
            # Keep the website open so the debug page can show the error.
            self.state.listener_failed(error)
        self._publisher_task = asyncio.create_task(
            self._publish_loop(), name="fh6-telemetry-publisher"
        )

    async def stop(self) -> None:
        # Stop new packets first, then finish the publisher and recorder.
        if self._transport is not None:
            self._transport.close()
            self._transport = None
            await asyncio.sleep(0)
        task, self._publisher_task = self._publisher_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self.recorder is not None:
            await asyncio.to_thread(self.recorder.stop)

    async def _publish_loop(self) -> None:
        # Keep dashboard updates steady even when packet timing jumps.
        interval = 1.0 / self.settings.telemetry_publish_hz
        loop = asyncio.get_running_loop()
        deadline = loop.time()
        while True:
            snapshot = self.state.realtime_snapshot()
            self.broadcaster.publish(snapshot)
            if self.recorder is not None:
                self.recorder.observe(
                    self.state.latest_packet,
                    self.state.revision,
                    bool(snapshot["connection"]["connected"]),  # type: ignore[index]
                )
            deadline += interval
            delay = deadline - loop.time()
            if delay <= 0:
                deadline = loop.time()
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(delay)
