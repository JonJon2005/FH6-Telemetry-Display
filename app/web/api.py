"""HTTP API routes kept separate from telemetry transport code."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.telemetry.service import LiveTelemetryService


router = APIRouter()


def _service(request: Request) -> LiveTelemetryService:
    return request.app.state.service


def _storage(request: Request):
    storage = request.app.state.storage
    if storage is None:
        # Tests can run the web app without creating permanent files.
        raise HTTPException(status_code=503, detail="Session storage is disabled for this runtime")
    return storage


@router.get("/api/telemetry")
async def telemetry_snapshot(request: Request) -> dict[str, object]:
    return _service(request).state.realtime_snapshot()


@router.get("/api/debug")
async def debug_snapshot(request: Request) -> dict[str, object]:
    snapshot = _service(request).state.snapshot()
    snapshot["network"] = request.app.state.network
    return snapshot


@router.get("/api/network")
async def network_status(request: Request) -> dict[str, object]:
    return request.app.state.network


@router.get("/api/recording")
async def recording_status(request: Request) -> dict[str, object]:
    recorder = request.app.state.recorder
    if recorder is None:
        return {"enabled": False, "running": False, "active_session_id": None}
    return recorder.status()


@router.get("/api/sessions")
async def sessions(request: Request, limit: int = Query(100, ge=1, le=500)) -> dict[str, object]:
    items = _storage(request).list_sessions(limit)
    return {"sessions": items, "count": len(items)}


@router.get("/api/sessions/{session_id}")
async def session(request: Request, session_id: str) -> dict[str, object]:
    item = _storage(request).get_session(session_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return item


@router.get("/api/sessions/{session_id}/export.csv")
async def export_session_csv(request: Request, session_id: str) -> StreamingResponse:
    storage = _storage(request)
    if storage.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return StreamingResponse(
        # Streaming keeps exports responsive for long drives.
        storage.iter_csv(session_id),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="fh6-session-{session_id}.csv"'},
    )


@router.get("/api/sessions/{session_id}/export.json")
async def export_session_json(request: Request, session_id: str) -> StreamingResponse:
    storage = _storage(request)
    if storage.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return StreamingResponse(
        storage.iter_json(session_id),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="fh6-session-{session_id}.json"'},
    )


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    service = _service(request)
    state = service.state
    listener_ok = state.listener_status == "listening"
    return {
        "status": "ok" if listener_ok else "degraded",
        "service_running": service.running,
        "udp_listener": state.listener_status,
        "udp_bind": state.bound_address,
        "udp_error": state.listener_error,
        "websocket_clients": service.websocket_clients,
        "telemetry_websocket_clients": service.broadcaster.active_clients,
        "debug_websocket_clients": service.debug_clients,
        "broadcast_hz": service.settings.telemetry_publish_hz,
        "broadcasts": service.broadcaster.published_count,
        "dropped_client_updates": service.broadcaster.dropped_updates,
        "recording": request.app.state.recorder.status() if request.app.state.recorder else {
            "enabled": False, "running": False, "active_session_id": None
        },
        "network": request.app.state.network,
    }
