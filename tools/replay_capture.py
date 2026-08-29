"""Replay a versioned FH6 raw capture to a UDP listener.

The utility validates the complete capture before sending anything, preserves
the exact UDP payload bytes, and schedules packets from their original receive
timestamps.  It does not decode or modify FH6 telemetry.
"""

from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import socket
import sys
import time
from typing import Callable, Iterator, TextIO

if __package__:
    from .udp_probe import CAPTURE_FORMAT, CAPTURE_VERSION, DEFAULT_PORT, port_number
else:  # Support the Windows-friendly: python tools\replay_capture.py ...
    from udp_probe import CAPTURE_FORMAT, CAPTURE_VERSION, DEFAULT_PORT, port_number


DEFAULT_TARGET_HOST = "127.0.0.1"
MAX_SLEEP_CHUNK_SECONDS = 0.25


class CaptureError(ValueError):
    """A capture is unreadable or violates the versioned file contract."""

    def __init__(self, path: Path, message: str, line_number: int | None = None) -> None:
        location = str(path)
        if line_number is not None:
            location += f":{line_number}"
        super().__init__(f"{location}: {message}")
        self.path = path
        self.line_number = line_number


@dataclass(frozen=True)
class CaptureHeader:
    format: str
    version: int
    created_at: str
    bind_host: str
    bind_port: int


@dataclass(frozen=True)
class CapturedPacket:
    received_at: str
    received_unix_ns: int
    source_ip: str
    source_port: int
    declared_length: int
    payload: bytes
    line_number: int


@dataclass(frozen=True)
class CaptureSummary:
    header: CaptureHeader
    packet_count: int
    payload_bytes: int
    recorded_duration_seconds: float
    length_counts: Counter[int]
    payload_sha256: str


@dataclass(frozen=True)
class ReplayStats:
    packets_sent: int
    payload_bytes_sent: int
    recorded_duration_seconds: float
    replay_duration_seconds: float
    nonmonotonic_timestamps: int
    payload_sha256: str


class CaptureReader:
    """Streaming reader for ``fh6cap-jsonl`` version 1 files."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.header: CaptureHeader | None = None
        self._file: TextIO | None = None
        self._line_number = 0

    def __enter__(self) -> "CaptureReader":
        try:
            self._file = self.path.open(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise CaptureError(self.path, f"cannot open capture: {exc}") from exc

        # The first line describes the capture before packet lines begin.
        line = self._file.readline()
        self._line_number = 1
        if not line:
            self.close()
            raise CaptureError(self.path, "capture is empty")
        record = self._parse_json(line, 1)
        self.header = self._parse_header(record, 1)
        return self

    def __iter__(self) -> Iterator[CapturedPacket]:
        if self._file is None or self.header is None:
            raise RuntimeError("CaptureReader must be used as a context manager")
        for line in self._file:
            self._line_number += 1
            if not line.strip():
                continue
            record = self._parse_json(line, self._line_number)
            yield self._parse_packet(record, self._line_number)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def __exit__(self, *_: object) -> None:
        self.close()

    def _parse_json(self, line: str, line_number: int) -> dict[str, object]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CaptureError(
                self.path,
                f"invalid JSON at column {exc.colno}: {exc.msg}",
                line_number,
            ) from exc
        if not isinstance(record, dict):
            raise CaptureError(self.path, "record must be a JSON object", line_number)
        return record

    def _parse_header(self, record: dict[str, object], line_number: int) -> CaptureHeader:
        if record.get("type") != "header":
            raise CaptureError(self.path, "first record must be a header", line_number)
        if record.get("format") != CAPTURE_FORMAT:
            raise CaptureError(
                self.path,
                f"unsupported capture format {record.get('format')!r}",
                line_number,
            )
        version = _required_int(record, "version", self.path, line_number)
        if version != CAPTURE_VERSION:
            raise CaptureError(
                self.path,
                f"unsupported {CAPTURE_FORMAT} version {version}; expected {CAPTURE_VERSION}",
                line_number,
            )
        created_at = _required_string(record, "created_at", self.path, line_number)
        bind_host = _required_string(record, "bind_host", self.path, line_number)
        bind_port = _required_int(record, "bind_port", self.path, line_number)
        if not 0 <= bind_port <= 65535:
            raise CaptureError(self.path, "bind_port must be between 0 and 65535", line_number)
        return CaptureHeader(
            format=CAPTURE_FORMAT,
            version=version,
            created_at=created_at,
            bind_host=bind_host,
            bind_port=bind_port,
        )

    def _parse_packet(self, record: dict[str, object], line_number: int) -> CapturedPacket:
        if record.get("type") != "packet":
            raise CaptureError(
                self.path,
                f"unsupported record type {record.get('type')!r}",
                line_number,
            )
        received_at = _required_string(record, "received_at", self.path, line_number)
        received_unix_ns = _required_int(
            record, "received_unix_ns", self.path, line_number
        )
        if received_unix_ns < 0:
            raise CaptureError(self.path, "received_unix_ns cannot be negative", line_number)
        source_ip = _required_string(record, "source_ip", self.path, line_number)
        source_port = _required_int(record, "source_port", self.path, line_number)
        if not 0 <= source_port <= 65535:
            raise CaptureError(self.path, "source_port must be between 0 and 65535", line_number)
        declared_length = _required_int(record, "length", self.path, line_number)
        if not 0 <= declared_length <= 65535:
            raise CaptureError(self.path, "length must be between 0 and 65535", line_number)
        encoded = _required_string(record, "payload_base64", self.path, line_number)
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CaptureError(self.path, "payload_base64 is invalid", line_number) from exc
        if len(payload) != declared_length:
            raise CaptureError(
                self.path,
                f"declared length {declared_length} does not match "
                f"decoded payload length {len(payload)}",
                line_number,
            )
        return CapturedPacket(
            received_at=received_at,
            received_unix_ns=received_unix_ns,
            source_ip=source_ip,
            source_port=source_port,
            declared_length=declared_length,
            payload=payload,
            line_number=line_number,
        )


def _required_string(
    record: dict[str, object], key: str, path: Path, line_number: int
) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value:
        raise CaptureError(path, f"{key} must be a non-empty string", line_number)
    return value


def _required_int(
    record: dict[str, object], key: str, path: Path, line_number: int
) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptureError(path, f"{key} must be an integer", line_number)
    return value


def inspect_capture(path: Path) -> CaptureSummary:
    """Validate a full capture and return constant-memory summary metadata."""
    # Hash all payloads so replay can prove nothing changed.
    packet_count = 0
    payload_bytes = 0
    first_ns: int | None = None
    last_ns: int | None = None
    length_counts: Counter[int] = Counter()
    digest = hashlib.sha256()

    with CaptureReader(path) as reader:
        assert reader.header is not None
        header = reader.header
        for packet in reader:
            packet_count += 1
            payload_bytes += len(packet.payload)
            length_counts[len(packet.payload)] += 1
            digest.update(packet.payload)
            if first_ns is None:
                first_ns = packet.received_unix_ns
            last_ns = packet.received_unix_ns

    if packet_count == 0 or first_ns is None or last_ns is None:
        raise CaptureError(path, "capture contains no packet records")
    duration = max(last_ns - first_ns, 0) / 1_000_000_000
    return CaptureSummary(
        header=header,
        packet_count=packet_count,
        payload_bytes=payload_bytes,
        recorded_duration_seconds=duration,
        length_counts=length_counts,
        payload_sha256=digest.hexdigest(),
    )


def replay_speed(value: str) -> float | None:
    """Parse a positive multiplier, optionally suffixed with x, or ``max``."""
    normalized = value.strip().lower()
    if normalized in {"max", "maximum"}:
        return None
    if normalized.endswith("x"):
        normalized = normalized[:-1]
    try:
        speed = float(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("speed must be a positive number or 'max'") from exc
    if speed <= 0:
        raise argparse.ArgumentTypeError("speed must be greater than zero")
    return speed


def format_speed(speed: float | None) -> str:
    return "maximum speed" if speed is None else f"{speed:g}x"


def _sleep_until(
    deadline: float,
    *,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
) -> None:
    """Sleep in short chunks so Ctrl+C remains responsive on Windows."""
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            return
        sleeper(min(remaining, MAX_SLEEP_CHUNK_SECONDS))


def replay_capture(
    path: Path,
    *,
    target_host: str = DEFAULT_TARGET_HOST,
    target_port: int = DEFAULT_PORT,
    speed: float | None = 1.0,
    output: TextIO = sys.stdout,
    clock: Callable[[], float] = time.perf_counter,
    sleeper: Callable[[float], None] = time.sleep,
    socket_factory: Callable[[], socket.socket] | None = None,
) -> ReplayStats:
    """Validate and replay *path* to the target, returning send statistics."""
    if speed is not None and speed <= 0:
        raise ValueError("speed must be greater than zero or None for maximum speed")
    summary = inspect_capture(path)
    # Validate the whole file before sending any UDP packets.
    print(f"Capture: {path}", file=output)
    print(
        f"Validated: {summary.packet_count:,} packets, "
        f"{summary.payload_bytes:,} payload bytes, "
        f"{summary.recorded_duration_seconds:.3f} recorded seconds",
        file=output,
    )
    print(f"Packet sizes: {dict(sorted(summary.length_counts.items()))}", file=output)
    print(f"Payload SHA-256: {summary.payload_sha256}", file=output)
    print(f"UDP target: {target_host}:{target_port}", file=output)
    print(f"Replay speed: {format_speed(speed)}", file=output, flush=True)

    if socket_factory is None:
        socket_factory = lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender = socket_factory()
    packets_sent = 0
    payload_bytes_sent = 0
    nonmonotonic_timestamps = 0
    first_capture_ns: int | None = None
    previous_offset_ns = 0
    replay_start = clock()
    digest = hashlib.sha256()

    try:
        with CaptureReader(path) as reader:
            for packet in reader:
                if first_capture_ns is None:
                    first_capture_ns = packet.received_unix_ns
                offset_ns = packet.received_unix_ns - first_capture_ns
                if offset_ns < previous_offset_ns:
                    # Never schedule a packet before the one ahead of it.
                    nonmonotonic_timestamps += 1
                    offset_ns = previous_offset_ns
                previous_offset_ns = offset_ns
                if speed is not None:
                    deadline = replay_start + (offset_ns / 1_000_000_000) / speed
                    _sleep_until(deadline, clock=clock, sleeper=sleeper)
                sent = sender.sendto(packet.payload, (target_host, target_port))
                if sent != len(packet.payload):
                    raise OSError(
                        f"UDP send accepted {sent} of {len(packet.payload)} payload bytes"
                    )
                digest.update(packet.payload)
                packets_sent += 1
                payload_bytes_sent += sent
    finally:
        sender.close()

    replay_duration = max(clock() - replay_start, 0.0)
    replay_digest = digest.hexdigest()
    if (
        packets_sent != summary.packet_count
        or payload_bytes_sent != summary.payload_bytes
        or replay_digest != summary.payload_sha256
    ):
        # This also catches a capture being edited during replay.
        raise CaptureError(path, "capture changed between validation and replay")

    stats = ReplayStats(
        packets_sent=packets_sent,
        payload_bytes_sent=payload_bytes_sent,
        recorded_duration_seconds=summary.recorded_duration_seconds,
        replay_duration_seconds=replay_duration,
        nonmonotonic_timestamps=nonmonotonic_timestamps,
        payload_sha256=replay_digest,
    )
    print("", file=output)
    print("Replay complete", file=output)
    print(f"  Packets sent: {stats.packets_sent:,}", file=output)
    print(f"  Payload bytes sent: {stats.payload_bytes_sent:,}", file=output)
    print(f"  Wall time: {stats.replay_duration_seconds:.3f} seconds", file=output)
    if stats.nonmonotonic_timestamps:
        print(
            f"  Timestamp corrections: {stats.nonmonotonic_timestamps:,}",
            file=output,
        )
    print(f"  Payload SHA-256: {stats.payload_sha256}", file=output, flush=True)
    return stats


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay a versioned FH6 raw capture to a UDP listener."
    )
    parser.add_argument("capture", type=Path, help="path to a .fh6cap file")
    parser.add_argument(
        "--host",
        default=DEFAULT_TARGET_HOST,
        help=f"destination host/IP (default: {DEFAULT_TARGET_HOST})",
    )
    parser.add_argument(
        "--port",
        type=port_number,
        default=DEFAULT_PORT,
        help=f"destination UDP port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--speed",
        type=replay_speed,
        default=1.0,
        metavar="MULTIPLIER|max",
        help="timing multiplier such as 0.5, 1, 2, or max (default: 1)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        replay_capture(
            args.capture,
            target_host=args.host,
            target_port=args.port,
            speed=args.speed,
        )
    except KeyboardInterrupt:
        print("\nReplay interrupted by Ctrl+C.", file=sys.stderr)
        return 130
    except (CaptureError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
