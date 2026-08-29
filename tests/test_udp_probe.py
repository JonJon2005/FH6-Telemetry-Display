from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket
import threading

import pytest

from tools.udp_probe import CaptureWriter, ProbeStats, hex_preview, port_number, run_probe


def test_hex_preview_is_bounded_and_marks_truncation() -> None:
    assert hex_preview(bytes.fromhex("00 ab ff 12"), 3) == "00 ab ff ..."
    assert hex_preview(b"", 32) == "(empty payload)"


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_port_number_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        port_number(value)


def test_stats_count_all_packet_lengths_and_calculate_rate() -> None:
    stats = ProbeStats(rate_window=2.0)
    received = datetime(2026, 8, 29, tzinfo=timezone.utc)
    stats.record(b"a" * 324, ("192.168.1.42", 5201), monotonic=10.0, received_at=received)
    assert stats.packets_per_second(10.0) == 0.0
    stats.record(b"odd", ("192.168.1.42", 5201), monotonic=10.5, received_at=received)

    assert stats.total_packets == 2
    assert stats.total_bytes == 327
    assert stats.sizes == {324: 1, 3: 1}
    assert stats.packets_per_second(11.0) == pytest.approx(2.0)
    assert stats.packets_per_second(13.0) == 0.0


def test_capture_is_versioned_jsonl_and_preserves_payload(tmp_path: Path) -> None:
    path = tmp_path / "sample.fh6cap"
    payload = bytes(range(256)) + b"tail"
    received = datetime(2026, 8, 29, 12, 30, tzinfo=timezone.utc)

    with CaptureWriter(path, bind_host="0.0.0.0", bind_port=20440) as capture:
        capture.write_packet(
            payload,
            ("192.168.1.42", 5277),
            received_at=received,
            received_unix_ns=1_777_000_000_123_456_789,
        )

    header, packet = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert header["format"] == "fh6cap-jsonl"
    assert header["version"] == 1
    assert packet["length"] == len(payload)
    assert packet["source_ip"] == "192.168.1.42"
    assert packet["source_port"] == 5277
    assert base64.b64decode(packet["payload_base64"]) == payload


def test_capture_refuses_to_overwrite_by_default(tmp_path: Path) -> None:
    path = tmp_path / "existing.fh6cap"
    path.write_text("keep me", encoding="utf-8")
    with pytest.raises(FileExistsError):
        CaptureWriter(path, bind_host="0.0.0.0", bind_port=20440)
    assert path.read_text(encoding="utf-8") == "keep me"


def test_udp_integration_accepts_unexpected_lengths(tmp_path: Path) -> None:
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    receiver.bind(("127.0.0.1", 0))
    port = receiver.getsockname()[1]
    receiver.close()

    ready = threading.Event()
    output = io.StringIO()
    capture_path = tmp_path / "integration.fh6cap"
    result: dict[str, ProbeStats] = {}

    def target() -> None:
        result["stats"] = run_probe(
            host="127.0.0.1",
            port=port,
            capture_path=capture_path,
            max_packets=2,
            output=output,
            ready_event=ready,
        )

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    assert ready.wait(timeout=2)

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.sendto(b"short", ("127.0.0.1", port))
        sender.sendto(b"x" * 324, ("127.0.0.1", port))

    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result["stats"].sizes == {5: 1, 324: 1}
    assert "Observed packet sizes" in output.getvalue()
    assert capture_path.exists()
