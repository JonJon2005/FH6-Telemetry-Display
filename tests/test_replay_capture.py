from __future__ import annotations

import argparse
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket

import pytest

from tools.replay_capture import (
    CaptureError,
    CaptureReader,
    inspect_capture,
    replay_capture,
    replay_speed,
)
from tools.udp_probe import CaptureWriter


RECEIVED = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def make_capture(
    path: Path,
    packets: list[tuple[int, bytes]],
) -> None:
    with CaptureWriter(path, bind_host="0.0.0.0", bind_port=20440) as writer:
        for index, (received_ns, payload) in enumerate(packets):
            writer.write_packet(
                payload,
                ("192.168.1.142", 5200 + index),
                received_at=RECEIVED,
                received_unix_ns=received_ns,
            )


def test_capture_reader_and_summary_preserve_packet_metadata(tmp_path: Path) -> None:
    path = tmp_path / "valid.fh6cap"
    make_capture(path, [(1_000_000_000, b"first"), (2_500_000_000, b"second")])

    with CaptureReader(path) as reader:
        assert reader.header is not None
        assert reader.header.bind_port == 20440
        packets = list(reader)

    assert [packet.payload for packet in packets] == [b"first", b"second"]
    assert [packet.source_port for packet in packets] == [5200, 5201]
    summary = inspect_capture(path)
    assert summary.packet_count == 2
    assert summary.payload_bytes == 11
    assert summary.recorded_duration_seconds == pytest.approx(1.5)
    assert summary.length_counts == {5: 1, 6: 1}


def test_reader_rejects_unsupported_version(tmp_path: Path) -> None:
    path = tmp_path / "future.fh6cap"
    path.write_text(
        json.dumps(
            {
                "type": "header",
                "format": "fh6cap-jsonl",
                "version": 99,
                "created_at": "2026-08-29T12:00:00Z",
                "bind_host": "0.0.0.0",
                "bind_port": 20440,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(CaptureError, match="unsupported fh6cap-jsonl version 99"):
        inspect_capture(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"length": 99}, "declared length 99"),
        ({"payload_base64": "%%%"}, "payload_base64 is invalid"),
        ({"received_unix_ns": "soon"}, "received_unix_ns must be an integer"),
    ],
)
def test_reader_rejects_invalid_packet_records(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    path = tmp_path / "invalid.fh6cap"
    make_capture(path, [(1_000_000_000, b"payload")])
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    records[1].update(mutation)
    path.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")

    with pytest.raises(CaptureError, match=message):
        inspect_capture(path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0.5", 0.5), ("1x", 1.0), ("2", 2.0), ("MAX", None)],
)
def test_replay_speed(text: str, expected: float | None) -> None:
    assert replay_speed(text) == expected


def test_replay_speed_rejects_invalid_values() -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        replay_speed("0")
    with pytest.raises(argparse.ArgumentTypeError):
        replay_speed("fast")


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleep_calls: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def sendto(self, payload: bytes, target: tuple[str, int]) -> int:
        self.sent.append((payload, target))
        return len(payload)

    def close(self) -> None:
        self.closed = True


def test_two_x_replay_uses_absolute_timing_without_drift(tmp_path: Path) -> None:
    path = tmp_path / "timed.fh6cap"
    make_capture(
        path,
        [
            (10_000_000_000, b"one"),
            (11_000_000_000, b"two"),
            (13_000_000_000, b"three"),
        ],
    )
    clock = FakeClock()
    sender = FakeSocket()

    stats = replay_capture(
        path,
        target_host="127.0.0.1",
        target_port=23456,
        speed=2.0,
        output=io.StringIO(),
        clock=clock,
        sleeper=clock.sleep,
        socket_factory=lambda: sender,  # type: ignore[arg-type]
    )

    assert [payload for payload, _ in sender.sent] == [b"one", b"two", b"three"]
    assert all(target == ("127.0.0.1", 23456) for _, target in sender.sent)
    assert sum(clock.sleep_calls) == pytest.approx(1.5)
    assert stats.replay_duration_seconds == pytest.approx(1.5)
    assert sender.closed


def test_max_speed_replay_over_real_udp_preserves_payloads(tmp_path: Path) -> None:
    path = tmp_path / "udp.fh6cap"
    expected = [b"short", bytes(range(256)) + b"tail", b"x" * 324]
    make_capture(path, [(1_000_000_000 + index, payload) for index, payload in enumerate(expected)])

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        receiver.bind(("127.0.0.1", 0))
        receiver.settimeout(2)
        port = receiver.getsockname()[1]
        stats = replay_capture(
            path,
            target_host="127.0.0.1",
            target_port=port,
            speed=None,
            output=io.StringIO(),
        )
        actual = [receiver.recvfrom(65535)[0] for _ in expected]

    assert actual == expected
    assert stats.packets_sent == len(expected)
    assert stats.payload_bytes_sent == sum(map(len, expected))
