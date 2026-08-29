"""SQLite session store and constant-memory export iterators."""

from __future__ import annotations

import csv
from datetime import datetime
import io
import json
import math
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import uuid4

from app.telemetry.models import TelemetryPacket


SCHEMA_VERSION = 1
SAMPLE_COLUMNS = (
    "captured_at", "elapsed_seconds", "game_timestamp_ms", "is_race_on",
    "lap_number", "race_position", "current_lap_seconds", "speed_mps", "rpm",
    "gear_raw", "throttle", "brake", "clutch", "handbrake", "steering",
    "tire_temp_fl_c", "tire_temp_fr_c", "tire_temp_rl_c", "tire_temp_rr_c",
    "accel_x", "accel_y", "accel_z", "position_x", "position_y", "position_z",
)


class SQLiteStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            # WAL lets the dashboard read while the recorder writes.
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    mode TEXT NOT NULL,
                    car_ordinal INTEGER,
                    car_class INTEGER,
                    performance_index INTEGER,
                    drivetrain TEXT,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    speed_sum_mps REAL NOT NULL DEFAULT 0,
                    max_speed_mps REAL NOT NULL DEFAULT 0,
                    max_rpm REAL NOT NULL DEFAULT 0,
                    best_lap_seconds REAL,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    end_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    captured_at TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    game_timestamp_ms INTEGER NOT NULL,
                    is_race_on INTEGER NOT NULL,
                    lap_number INTEGER NOT NULL,
                    race_position INTEGER NOT NULL,
                    current_lap_seconds REAL NOT NULL,
                    speed_mps REAL NOT NULL,
                    rpm REAL NOT NULL,
                    gear_raw INTEGER NOT NULL,
                    throttle REAL NOT NULL,
                    brake REAL NOT NULL,
                    clutch REAL NOT NULL,
                    handbrake REAL NOT NULL,
                    steering REAL NOT NULL,
                    tire_temp_fl_c REAL NOT NULL,
                    tire_temp_fr_c REAL NOT NULL,
                    tire_temp_rl_c REAL NOT NULL,
                    tire_temp_rr_c REAL NOT NULL,
                    accel_x REAL NOT NULL,
                    accel_y REAL NOT NULL,
                    accel_z REAL NOT NULL,
                    position_x REAL NOT NULL,
                    position_y REAL NOT NULL,
                    position_z REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS samples_by_session ON samples(session_id, id);
                """
            )
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def open_writer(self) -> "SessionWriter":
        return SessionWriter(self._connect())

    def list_sessions(self, limit: int = 100) -> list[dict[str, object]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_session_dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return _session_dict(row) if row else None

    def iter_csv(self, session_id: str) -> Iterator[str]:
        # Yield one row at a time so long sessions do not fill memory.
        connection = self._connect()
        try:
            output = io.StringIO()
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(("session_id", *SAMPLE_COLUMNS))
            yield output.getvalue()
            cursor = connection.execute(
                f"SELECT {', '.join(SAMPLE_COLUMNS)} FROM samples WHERE session_id = ? ORDER BY id",
                (session_id,),
            )
            for row in cursor:
                output.seek(0)
                output.truncate()
                writer.writerow((session_id, *(row[column] for column in SAMPLE_COLUMNS)))
                yield output.getvalue()
        finally:
            connection.close()

    def iter_json(self, session_id: str) -> Iterator[str]:
        session = self.get_session(session_id)
        if session is None:
            return
        connection = self._connect()
        try:
            # Build valid JSON in small pieces instead of one large list.
            yield '{"session":' + json.dumps(session, allow_nan=False) + ',"samples":['
            cursor = connection.execute(
                f"SELECT {', '.join(SAMPLE_COLUMNS)} FROM samples WHERE session_id = ? ORDER BY id",
                (session_id,),
            )
            first = True
            for row in cursor:
                sample = {column: row[column] for column in SAMPLE_COLUMNS}
                yield ("" if first else ",") + json.dumps(sample, allow_nan=False, separators=(",", ":"))
                first = False
            yield "]}"
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection


class SessionWriter:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def start_session(self, packet: TelemetryPacket, started_at: datetime) -> str:
        session_id = str(uuid4())
        vehicle = packet.vehicle
        self.connection.execute(
            """INSERT INTO sessions
               (id, started_at, mode, car_ordinal, car_class, performance_index, drivetrain)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id, started_at.isoformat(), _mode(packet), vehicle.car_ordinal,
                vehicle.car_class, vehicle.performance_index, vehicle.drivetrain.label,
            ),
        )
        self.connection.commit()
        return session_id

    def add_sample(
        self, session_id: str, packet: TelemetryPacket, captured_at: datetime, elapsed: float
    ) -> None:
        values = _sample_values(packet, captured_at, elapsed)
        # Save the sample and update its summary in the same commit.
        self.connection.execute(
            f"INSERT INTO samples (session_id, {', '.join(SAMPLE_COLUMNS)}) VALUES ({', '.join('?' for _ in range(len(SAMPLE_COLUMNS) + 1))})",
            (session_id, *values),
        )
        best_lap = _best_lap(packet)
        self.connection.execute(
            """UPDATE sessions SET
               sample_count = sample_count + 1,
               speed_sum_mps = speed_sum_mps + ?,
               max_speed_mps = MAX(max_speed_mps, ?),
               max_rpm = MAX(max_rpm, ?),
               best_lap_seconds = CASE
                 WHEN ? IS NULL THEN best_lap_seconds
                 WHEN best_lap_seconds IS NULL OR ? < best_lap_seconds THEN ?
                 ELSE best_lap_seconds END,
               duration_seconds = MAX(duration_seconds, ?),
               mode = CASE WHEN ? THEN 'race' ELSE mode END
               WHERE id = ?""",
            (
                _finite(packet.vehicle.speed.meters_per_second),
                _finite(packet.vehicle.speed.meters_per_second),
                _finite(packet.vehicle.current_engine_rpm),
                best_lap, best_lap, best_lap, max(0.0, elapsed), packet.race.is_race_on, session_id,
            ),
        )
        self.connection.commit()

    def end_session(self, session_id: str, ended_at: datetime, elapsed: float, reason: str) -> None:
        self.connection.execute(
            "UPDATE sessions SET ended_at = ?, duration_seconds = MAX(duration_seconds, ?), end_reason = ? WHERE id = ?",
            (ended_at.isoformat(), max(0.0, elapsed), reason, session_id),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


def _sample_values(packet: TelemetryPacket, captured_at: datetime, elapsed: float) -> tuple[object, ...]:
    race, vehicle, inputs = packet.race, packet.vehicle, packet.inputs
    motion, position, wheels = packet.motion, packet.position, packet.wheels
    return (
        captured_at.isoformat(), max(0.0, elapsed), race.timestamp_ms, int(race.is_race_on),
        race.lap_number, race.race_position, _finite(race.current_lap_seconds),
        _finite(vehicle.speed.meters_per_second), _finite(vehicle.current_engine_rpm), inputs.gear.raw,
        _finite(inputs.throttle.normalized), _finite(inputs.brake.normalized),
        _finite(inputs.clutch.normalized), _finite(inputs.handbrake.normalized),
        _finite(inputs.steering.normalized),
        _finite(wheels.front_left.tire_temperature.celsius),
        _finite(wheels.front_right.tire_temperature.celsius),
        _finite(wheels.rear_left.tire_temperature.celsius),
        _finite(wheels.rear_right.tire_temperature.celsius),
        _finite(motion.acceleration_source.x), _finite(motion.acceleration_source.y),
        _finite(motion.acceleration_source.z), _finite(position.world_meters.x),
        _finite(position.world_meters.y), _finite(position.world_meters.z),
    )


def _session_dict(row: sqlite3.Row) -> dict[str, object]:
    result = dict(row)
    count = int(result["sample_count"])
    average = float(result.pop("speed_sum_mps")) / count if count else 0.0
    result["average_speed_mps"] = average
    result["average_speed_mph"] = average * 2.2369362920544
    result["max_speed_mph"] = float(result["max_speed_mps"]) * 2.2369362920544
    return result


def _mode(packet: TelemetryPacket) -> str:
    return "race" if packet.race.is_race_on else "free_roam"


def _best_lap(packet: TelemetryPacket) -> float | None:
    value = packet.race.best_lap_seconds
    return value if math.isfinite(value) and value > 0 else None


def _finite(value: float) -> float:
    # SQLite and JSON exports are safer without NaN or infinity values.
    return float(value) if math.isfinite(value) else 0.0
