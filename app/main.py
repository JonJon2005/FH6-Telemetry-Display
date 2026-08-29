"""FastAPI application factory and Windows-friendly entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.config import Settings
from app.network import NetworkDiscovery, discover_lan_ipv4, startup_lines
from app.runtime.config_file import ensure_default_config, load_settings
from app.runtime.logging_setup import configure_logging
from app.runtime.paths import AppPaths
from app.runtime.single_instance import SingleInstanceLock
from app.sessions import SessionRecorder, SQLiteStorage
from app.telemetry.service import LiveTelemetryService
from app.web.api import router as api_router
from app.web.websocket import router as websocket_router


WEB_ROOT = Path(__file__).resolve().parent / "web" / "static"
logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    network_discovery: NetworkDiscovery | None = None,
    *,
    announce: bool = True,
    app_paths: AppPaths | None = None,
    manage_runtime: bool | None = None,
) -> FastAPI:
    paths = app_paths or AppPaths.discover()
    managed = settings is None if manage_runtime is None else manage_runtime
    if settings is None:
        # Wait until startup before creating files on the computer.
        runtime = (
            load_settings(paths, save_migration=False)
            if paths.config_file.exists()
            else Settings.from_env()
        )
    else:
        runtime = settings
    service = LiveTelemetryService(runtime)
    storage: SQLiteStorage | None = None
    recorder: SessionRecorder | None = None
    instance_lock: SingleInstanceLock | None = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal storage, recorder, instance_lock
        try:
            if managed:
                # Set up everything the packaged app needs in the background.
                paths.ensure()
                ensure_default_config(paths)
                # Save any one-time config migration now that the app is starting.
                load_settings(paths)
                configure_logging(paths, runtime)
                instance_lock = SingleInstanceLock(paths.lock_file)
                instance_lock.acquire()
                storage = SQLiteStorage(paths.database_file)
                storage.initialize()
                recorder = SessionRecorder(storage, runtime)
                service.recorder = recorder
                application.state.storage = storage
                application.state.recorder = recorder
                application.state.instance_lock = instance_lock
                logger.info("Runtime data: %s", paths.base_dir)
            await service.start()
            try:
                discovered = network_discovery or await asyncio.to_thread(
                    discover_lan_ipv4, runtime.lan_ip_override
                )
                application.state.network_discovery = discovered
                application.state.network = discovered.endpoint_status(runtime)
                if announce:
                    print("\n".join(startup_lines(runtime, discovered)), flush=True)
                    if managed:
                        print(f"Data folder: {paths.base_dir}", flush=True)
                yield
            finally:
                await service.stop()
        finally:
            if instance_lock is not None:
                instance_lock.release()
                instance_lock = None
            logger.info("FH6 Telemetry stopped cleanly")

    application = FastAPI(title="FH6 Telemetry Service", version="0.9.0", lifespan=lifespan)
    application.state.service = service
    # Keep the telemetry state easy to reach from tests and helper tools.
    application.state.telemetry = service.state
    application.state.settings = runtime
    application.state.paths = paths if managed else None
    application.state.storage = None
    application.state.recorder = None
    application.state.instance_lock = None
    application.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
    application.include_router(api_router)
    application.include_router(websocket_router)

    @application.get("/", include_in_schema=False)
    async def home() -> RedirectResponse:
        return RedirectResponse("/dashboard")

    @application.get("/dashboard", include_in_schema=False)
    async def dashboard_page() -> FileResponse:
        return FileResponse(WEB_ROOT / "dashboard.html")

    @application.get("/debug", include_in_schema=False)
    async def debug_page() -> FileResponse:
        return FileResponse(WEB_ROOT / "debug.html")

    return application


app = create_app()


def main() -> None:
    paths = AppPaths.discover()
    paths.ensure()
    ensure_default_config(paths)
    settings = load_settings(paths)
    configure_logging(paths, settings)
    uvicorn.run(
        create_app(settings, app_paths=paths, manage_runtime=True),
        host=settings.http_host,
        port=settings.http_port,
        log_config=None,
    )


if __name__ == "__main__":
    main()
