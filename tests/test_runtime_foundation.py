from __future__ import annotations

import json
import logging
from pathlib import Path
import socket
import time

import pytest
from starlette.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.network import AdapterAddress, NetworkDiscovery
from app.runtime.config_file import ensure_default_config, load_settings
from app.runtime.logging_setup import configure_logging
from app.runtime.paths import AppPaths
from app.runtime.single_instance import AlreadyRunningError, SingleInstanceLock
from app.sessions.storage import SQLiteStorage
from tests.test_validation import valid_packet
from tools.replay_capture import CaptureReader


TEST_ADAPTER = AdapterAddress("192.168.1.205", "Ethernet", 4, 10, 25, True, "test")
TEST_NETWORK = NetworkDiscovery(TEST_ADAPTER, (TEST_ADAPTER,), ())


def test_config_file_is_created_and_environment_wins(tmp_path, monkeypatch) -> None:
    paths = AppPaths.from_base(tmp_path / "profile")
    paths.ensure()
    ensure_default_config(paths)
    payload = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert payload["version"] == 2
    assert payload["recording_hz"] == 5.0

    payload["udp_port"] = 21111
    payload["recording_enabled"] = False
    paths.config_file.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("FH6_UDP_PORT", "22222")
    settings = load_settings(paths)
    assert settings.udp_port == 22222
    assert settings.recording_enabled is False


def test_old_default_http_port_is_migrated(tmp_path) -> None:
    paths = AppPaths.from_base(tmp_path / "old-profile")
    paths.ensure()
    paths.config_file.write_text(
        json.dumps({"version": 1, "http_port": 8080}), encoding="utf-8"
    )

    settings = load_settings(paths)

    assert settings.http_port == 50415
    saved = json.loads(paths.config_file.read_text(encoding="utf-8"))
    assert saved == {"version": 2, "http_port": 50415}


def test_single_instance_lock_releases_cleanly(tmp_path) -> None:
    path = tmp_path / "app.lock"
    first = SingleInstanceLock(path)
    second = SingleInstanceLock(path)
    first.acquire()
    with pytest.raises(AlreadyRunningError):
        second.acquire()
    first.release()
    second.acquire()
    second.release()


def test_rotating_log_is_bounded(tmp_path) -> None:
    paths = AppPaths.from_base(tmp_path / "profile")
    settings = Settings(log_max_bytes=256, log_backup_count=2)
    configure_logging(paths, settings)
    logger = logging.getLogger("fh6.rotation.test")
    for index in range(40):
        logger.info("rotation line %s %s", index, "x" * 80)
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert (paths.logs_dir / "fh6-telemetry.log").exists()
    assert len(list(paths.logs_dir.glob("fh6-telemetry.log*"))) <= 3


def test_managed_app_records_exports_and_finalizes_session(tmp_path) -> None:
    paths = AppPaths.from_base(tmp_path / "profile")
    settings = Settings(
        udp_host="127.0.0.1",
        udp_port=0,
        telemetry_publish_hz=100,
        recording_hz=60,
        session_end_timeout_seconds=1,
        log_max_bytes=10_000,
    )
    app = create_app(
        settings,
        TEST_NETWORK,
        announce=False,
        app_paths=paths,
        manage_runtime=True,
    )
    with TestClient(app) as client:
        port = int(app.state.telemetry.bound_address.rsplit(":", 1)[1])
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            for _ in range(5):
                sender.sendto(bytes(valid_packet()), ("127.0.0.1", port))
                time.sleep(0.025)
        finally:
            sender.close()

        deadline = time.monotonic() + 2
        status = client.get("/api/recording").json()
        while status.get("active_sample_count", 0) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
            status = client.get("/api/recording").json()
        assert status["running"] is True
        assert status["active_sample_count"] >= 2

        sessions = client.get("/api/sessions").json()["sessions"]
        assert len(sessions) == 1
        session_id = sessions[0]["id"]
        assert sessions[0]["sample_count"] >= 2
        csv_export = client.get(f"/api/sessions/{session_id}/export.csv")
        assert csv_export.status_code == 200
        assert csv_export.text.startswith("session_id,captured_at,")
        json_export = client.get(f"/api/sessions/{session_id}/export.json")
        exported = json_export.json()
        assert exported["session"]["id"] == session_id
        assert len(exported["samples"]) >= 2

    storage = SQLiteStorage(paths.database_file)
    finished = storage.list_sessions()[0]
    assert finished["ended_at"] is not None
    assert finished["end_reason"] == "service_shutdown"
    assert paths.config_file.exists()
    assert (paths.logs_dir / "fh6-telemetry.log").exists()


def test_unmanaged_app_reports_recording_disabled() -> None:
    app = create_app(
        Settings(udp_host="127.0.0.1", udp_port=0),
        TEST_NETWORK,
        announce=False,
    )
    with TestClient(app) as client:
        assert client.get("/api/recording").json()["enabled"] is False
        assert client.get("/api/sessions").status_code == 503


def test_session_ends_at_last_packet_after_timeout(tmp_path) -> None:
    paths = AppPaths.from_base(tmp_path / "timeout-profile")
    settings = Settings(
        udp_host="127.0.0.1",
        udp_port=0,
        telemetry_publish_hz=100,
        recording_hz=60,
        session_end_timeout_seconds=0.1,
    )
    app = create_app(settings, TEST_NETWORK, announce=False, app_paths=paths, manage_runtime=True)
    with TestClient(app) as client:
        port = int(app.state.telemetry.bound_address.rsplit(":", 1)[1])
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sender.sendto(bytes(valid_packet()), ("127.0.0.1", port))
        finally:
            sender.close()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            sessions = client.get("/api/sessions").json()["sessions"]
            if sessions and sessions[0]["end_reason"] == "telemetry_timeout":
                break
            time.sleep(0.02)
        assert sessions[0]["end_reason"] == "telemetry_timeout"
        assert sessions[0]["duration_seconds"] < 0.05


def test_first_real_capture_records_multiple_samples(tmp_path) -> None:
    capture_path = Path(__file__).parents[1] / "captures" / "first-drive.fh6cap"
    paths = AppPaths.from_base(tmp_path / "capture-profile")
    settings = Settings(
        udp_host="127.0.0.1",
        udp_port=0,
        telemetry_publish_hz=120,
        recording_hz=60,
        session_end_timeout_seconds=1,
    )
    app = create_app(settings, TEST_NETWORK, announce=False, app_paths=paths, manage_runtime=True)
    with TestClient(app):
        port = int(app.state.telemetry.bound_address.rsplit(":", 1)[1])
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            with CaptureReader(capture_path) as reader:
                for index, packet in enumerate(reader):
                    if index == 50:
                        break
                    sender.sendto(packet.payload, ("127.0.0.1", port))
                    time.sleep(0.012)
        finally:
            sender.close()
        deadline = time.monotonic() + 2
        while app.state.recorder.status()["active_sample_count"] < 10 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert app.state.recorder.status()["active_sample_count"] >= 10

    session = SQLiteStorage(paths.database_file).list_sessions()[0]
    assert session["sample_count"] >= 10
    assert session["end_reason"] == "service_shutdown"
