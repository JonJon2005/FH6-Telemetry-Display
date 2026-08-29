"""Asyncio UDP protocol for live FH6 packets."""

from __future__ import annotations

import asyncio

from .state import TelemetryState


class TelemetryUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, state: TelemetryState) -> None:
        self.state = state

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        address = transport.get_extra_info("sockname")
        self.state.listener_ready(str(address[0]), int(address[1]))

    def datagram_received(self, data: bytes, address: tuple[str, int]) -> None:
        # The shared state handles parsing and packet counts.
        self.state.handle_datagram(data, address)

    def error_received(self, error: Exception) -> None:
        self.state.listener_error = str(error)

    def connection_lost(self, error: Exception | None) -> None:
        self.state.listener_status = "stopped" if error is None else "error"
        if error is not None:
            self.state.listener_error = str(error)
