"""Non-blocking bridge from realtime telemetry to the SQLite writer thread."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from queue import Empty, Full, Queue
import threading
import time

from app.config import Settings
from app.telemetry.models import TelemetryPacket
from .storage import SQLiteStorage


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RecorderEvent:
    packet: TelemetryPacket | None
    revision: int
    connected: bool
    observed_monotonic: float
    observed_at: datetime


class SessionRecorder:
    def __init__(self, storage: SQLiteStorage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings
        self._queue: Queue[RecorderEvent | None] = Queue(maxsize=1)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._active_session_id: str | None = None
        self._active_started_at: str | None = None
        self._sample_count = 0
        self._dropped_events = 0
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.settings.recording_enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="fh6-session-recorder", daemon=False)
        self._thread.start()

    def observe(self, packet: TelemetryPacket | None, revision: int, connected: bool) -> None:
        if self._thread is None:
            return
        event = RecorderEvent(packet, revision, connected, time.monotonic(), datetime.now(timezone.utc))
        try:
            self._queue.put_nowait(event)
        except Full:
            # Drop the old update instead of slowing down live telemetry.
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            try:
                self._queue.put_nowait(event)
            except Full:
                pass
            with self._lock:
                self._dropped_events += 1

    def stop(self, timeout: float = 5.0) -> None:
        thread, self._thread = self._thread, None
        if thread is None:
            return
        while True:
            try:
                self._queue.put_nowait(None)
                break
            except Full:
                try:
                    self._queue.get_nowait()
                except Empty:
                    pass
        thread.join(timeout)
        if thread.is_alive():
            logger.error("Session recorder did not stop within %.1f seconds", timeout)

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "enabled": self.settings.recording_enabled,
                "running": self._thread is not None and self._thread.is_alive(),
                "recording_hz": self.settings.recording_hz,
                "active_session_id": self._active_session_id,
                "active_started_at": self._active_started_at,
                "active_sample_count": self._sample_count,
                "dropped_events": self._dropped_events,
                "last_error": self._last_error,
            }

    def _run(self) -> None:
        # All database writes stay on this one background thread.
        writer = self.storage.open_writer()
        session_id: str | None = None
        started_monotonic = 0.0
        last_seen = 0.0
        last_seen_at: datetime | None = None
        next_sample = 0.0
        last_sample_revision = -1
        last_observed_revision = -1
        car_ordinal: int | None = None
        try:
            while True:
                try:
                    event = self._queue.get(timeout=0.25)
                except Empty:
                    event = None
                    stopping = False
                else:
                    stopping = event is None
                now = time.monotonic()
                if stopping:
                    if session_id:
                        writer.end_session(
                            session_id,
                            last_seen_at or datetime.now(timezone.utc),
                            max(0.0, last_seen - started_monotonic),
                            "service_shutdown",
                        )
                    break
                is_new_packet = (
                    event is not None
                    and event.connected
                    and event.packet is not None
                    and event.revision != last_observed_revision
                )
                if is_new_packet and event is not None and event.packet is not None:
                    packet = event.packet
                    last_seen = event.observed_monotonic
                    last_seen_at = event.observed_at
                    last_observed_revision = event.revision
                    current_car = packet.vehicle.car_ordinal
                    if session_id and car_ordinal not in (None, 0) and current_car not in (0, car_ordinal):
                        # A different car starts a clean session.
                        writer.end_session(session_id, event.observed_at, event.observed_monotonic - started_monotonic, "car_changed")
                        session_id = None
                    if session_id is None:
                        session_id = writer.start_session(packet, event.observed_at)
                        started_monotonic = event.observed_monotonic
                        next_sample = event.observed_monotonic
                        last_sample_revision = -1
                        car_ordinal = current_car
                        self._set_active(session_id, event.observed_at.isoformat(), 0)
                    if event.revision != last_sample_revision and event.observed_monotonic >= next_sample:
                        writer.add_sample(session_id, packet, event.observed_at, event.observed_monotonic - started_monotonic)
                        last_sample_revision = event.revision
                        next_sample = event.observed_monotonic + 1.0 / self.settings.recording_hz
                        with self._lock:
                            self._sample_count += 1
                elif session_id and last_seen and now - last_seen >= self.settings.session_end_timeout_seconds:
                    # End at the last real packet, not after the silent wait.
                    writer.end_session(
                        session_id,
                        last_seen_at or datetime.now(timezone.utc),
                        max(0.0, last_seen - started_monotonic),
                        "telemetry_timeout",
                    )
                    session_id = None
                    self._set_active(None, None, 0)
        except Exception as error:
            logger.exception("Session recorder failed")
            with self._lock:
                self._last_error = str(error)
        finally:
            writer.close()
            self._set_active(None, None, 0)

    def _set_active(self, session_id: str | None, started_at: str | None, count: int) -> None:
        with self._lock:
            self._active_session_id = session_id
            self._active_started_at = started_at
            self._sample_count = count
