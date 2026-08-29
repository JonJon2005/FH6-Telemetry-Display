"""Realtime and diagnostic WebSocket routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.telemetry.service import LiveTelemetryService


router = APIRouter()


@router.websocket("/ws/telemetry")
async def telemetry_socket(websocket: WebSocket) -> None:
    service: LiveTelemetryService = websocket.app.state.service
    await websocket.accept()
    queue = service.subscribe_realtime()
    if queue is None:
        await websocket.close(code=1013, reason="telemetry client limit reached")
        return
    try:
        # Send one snapshot if the regular publisher has not started yet.
        if queue.empty():
            service.broadcaster.publish(service.state.realtime_snapshot())
        while True:
            snapshot = await queue.get()
            await asyncio.wait_for(
                websocket.send_json(snapshot),
                timeout=service.settings.websocket_send_timeout_seconds,
            )
    except (WebSocketDisconnect, RuntimeError, TimeoutError):
        return
    finally:
        service.broadcaster.unsubscribe(queue)


@router.websocket("/ws/debug")
async def debug_socket(websocket: WebSocket) -> None:
    service: LiveTelemetryService = websocket.app.state.service
    await websocket.accept()
    if not service.add_debug_client():
        await websocket.close(code=1013, reason="telemetry client limit reached")
        return
    interval = 1.0 / service.settings.debug_push_hz
    try:
        # Debug data changes less often, so it uses its own slower rate.
        while True:
            await asyncio.wait_for(
                websocket.send_json(service.state.snapshot()),
                timeout=service.settings.websocket_send_timeout_seconds,
            )
            await asyncio.sleep(interval)
    except (WebSocketDisconnect, RuntimeError, TimeoutError):
        return
    finally:
        service.remove_debug_client()
