"""Inspect and optionally capture raw Forza Horizon 6 UDP telemetry.

This tool deliberately does not parse telemetry.  Its job is to report what is
actually arriving on the wire and to preserve byte-exact payloads for later
protocol validation.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys
import threading
import time
from typing import Callable, TextIO


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 20440
DEFAULT_HEX_BYTES = 32
DEFAULT_STOP_TIMEOUT = 2.0
CAPTURE_FORMAT = "fh6cap-jsonl"
CAPTURE_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    """Return an ISO-8601 UTC timestamp using the familiar Z suffix."""
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def port_number(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a number") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be an integer") from exc
    if number < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return number


def hex_preview(payload: bytes, limit: int = DEFAULT_HEX_BYTES) -> str:
    """Format up to *limit* bytes without assuming a packet layout."""
    shown = payload[:limit]
    result = " ".join(f"{byte:02x}" for byte in shown)
    if len(payload) > limit:
        result += " ..."
    return result or "(empty payload)"


@dataclass
class ProbeStats:
    """Bounded in-memory receiver statistics."""

    rate_window: float = 2.0
    total_packets: int = 0
    total_bytes: int = 0
    sizes: Counter[int] = field(default_factory=Counter)
    senders: Counter[tuple[str, int]] = field(default_factory=Counter)
    first_monotonic: float | None = None
    last_monotonic: float | None = None
    first_received_at: datetime | None = None
    last_received_at: datetime | None = None
    _recent: deque[float] = field(default_factory=deque, repr=False)

    def record(
        self,
        payload: bytes,
        sender: tuple[str, int],
        *,
        monotonic: float,
        received_at: datetime,
    ) -> None:
        if self.first_monotonic is None:
            self.first_monotonic = monotonic
            self.first_received_at = received_at
        self.last_monotonic = monotonic
        self.last_received_at = received_at
        self.total_packets += 1
        self.total_bytes += len(payload)
        self.sizes[len(payload)] += 1
        self.senders[sender] += 1
        self._recent.append(monotonic)
        self._prune(monotonic)

    def packets_per_second(self, now: float) -> float:
        self._prune(now)
        if not self._recent or self.first_monotonic is None:
            return 0.0
        elapsed_since_first = now - self.first_monotonic
        if elapsed_since_first <= 0:
            return 0.0
        elapsed = min(self.rate_window, elapsed_since_first)
        return len(self._recent) / elapsed

    def _prune(self, now: float) -> None:
        # Only keep timestamps needed for the current rate.
        cutoff = now - self.rate_window
        while self._recent and self._recent[0] < cutoff:
            self._recent.popleft()


class CaptureWriter:
    """Write the versioned, newline-delimited JSON capture format."""

    def __init__(
        self,
        path: Path,
        *,
        bind_host: str,
        bind_port: int,
        overwrite: bool = False,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Do not replace a capture unless --overwrite was requested.
        mode = "w" if overwrite else "x"
        self.path = path
        self._file: TextIO = path.open(mode, encoding="utf-8", newline="\n")
        self._write(
            {
                "type": "header",
                "format": CAPTURE_FORMAT,
                "version": CAPTURE_VERSION,
                "created_at": iso_utc(utc_now()),
                "bind_host": bind_host,
                "bind_port": bind_port,
            }
        )

    def write_packet(
        self,
        payload: bytes,
        sender: tuple[str, int],
        *,
        received_at: datetime,
        received_unix_ns: int,
    ) -> None:
        self._write(
            {
                "type": "packet",
                "received_at": iso_utc(received_at),
                "received_unix_ns": received_unix_ns,
                "source_ip": sender[0],
                "source_port": sender[1],
                "length": len(payload),
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            }
        )

    def _write(self, record: dict[str, object]) -> None:
        # Flush each packet so Ctrl+C or a crash loses as little as possible.
        self._file.write(json.dumps(record, separators=(",", ":")) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "CaptureWriter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def packet_report(
    *,
    payload: bytes,
    sender: tuple[str, int],
    received_at: datetime,
    rate: float,
    hex_bytes: int,
) -> str:
    return "\n".join(
        (
            "Packet received",
            f"  Time: {iso_utc(received_at)}",
            f"  Source: {sender[0]}:{sender[1]}",
            f"  Length: {len(payload)} bytes",
            f"  Packets/sec: {rate:.1f}",
            f"  First {min(hex_bytes, len(payload))} bytes: {hex_preview(payload, hex_bytes)}",
        )
    )


def final_summary(stats: ProbeStats, now: float) -> str:
    lines = ["", "Final summary", f"  Total packets: {stats.total_packets:,}"]
    lines.append(f"  Total payload bytes: {stats.total_bytes:,}")
    if stats.first_received_at is not None:
        lines.append(f"  First packet: {iso_utc(stats.first_received_at)}")
    if stats.last_received_at is not None:
        lines.append(f"  Last packet: {iso_utc(stats.last_received_at)}")
    if stats.first_monotonic is not None:
        elapsed = max(now - stats.first_monotonic, 0.0)
        lines.append(f"  Elapsed since first packet: {elapsed:.1f} s")
    lines.append("  Observed packet sizes:")
    if stats.sizes:
        lines.extend(f"    {size}: {count:,} packets" for size, count in sorted(stats.sizes.items()))
    else:
        lines.append("    (none)")
    lines.append("  Observed senders:")
    if stats.senders:
        lines.extend(
            f"    {ip}:{port}: {count:,} packets"
            for (ip, port), count in sorted(stats.senders.items())
        )
    else:
        lines.append("    (none)")
    return "\n".join(lines)


def run_probe(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    capture_path: Path | None = None,
    overwrite: bool = False,
    hex_bytes: int = DEFAULT_HEX_BYTES,
    stop_timeout: float = DEFAULT_STOP_TIMEOUT,
    verbose: bool = False,
    max_packets: int | None = None,
    output: TextIO = sys.stdout,
    ready_event: threading.Event | None = None,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> ProbeStats:
    """Run until Ctrl+C or *max_packets* is reached (the latter helps tests)."""
    stats = ProbeStats()
    capture: CaptureWriter | None = None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # A short timeout lets the loop notice silence and Ctrl+C quickly.
    sock.settimeout(min(0.25, stop_timeout / 4))
    try:
        sock.bind((host, port))
        actual_host, actual_port = sock.getsockname()[:2]
        if capture_path is not None:
            capture = CaptureWriter(
                capture_path,
                bind_host=str(actual_host),
                bind_port=int(actual_port),
                overwrite=overwrite,
            )
        print(f"FH6 UDP receiver listening on {actual_host}:{actual_port}", file=output)
        print("No packet length is assumed; every datagram will be counted.", file=output)
        if capture is not None:
            print(f"Capturing byte-exact packets to {capture.path}", file=output)
        print("Press Ctrl+C to stop and print a summary.\n", file=output, flush=True)
        if ready_event is not None:
            ready_event.set()

        last_display = 0.0
        stopped_reported = False
        last_payload = b""
        last_sender = ("", 0)

        while max_packets is None or stats.total_packets < max_packets:
            try:
                payload, sender = sock.recvfrom(65535)
            except socket.timeout:
                now = monotonic_clock()
                if (
                    stats.last_monotonic is not None
                    and now - stats.last_monotonic >= stop_timeout
                    and not stopped_reported
                ):
                    print(
                        f"WARNING: telemetry traffic stopped; no packet for "
                        f"{now - stats.last_monotonic:.1f} seconds.",
                        file=output,
                        flush=True,
                    )
                    stopped_reported = True
                continue

            received_at = utc_now()
            received_ns = time.time_ns()
            now = monotonic_clock()
            stats.record(payload, sender, monotonic=now, received_at=received_at)
            if capture is not None:
                capture.write_packet(
                    payload,
                    sender,
                    received_at=received_at,
                    received_unix_ns=received_ns,
                )

            if stopped_reported:
                print("Telemetry traffic resumed.", file=output)
                stopped_reported = False

            source_or_size_changed = sender != last_sender or len(payload) != len(last_payload)
            # Normal mode prints useful changes and one update per second.
            if verbose or stats.total_packets == 1 or source_or_size_changed or now - last_display >= 1.0:
                print(
                    packet_report(
                        payload=payload,
                        sender=sender,
                        received_at=received_at,
                        rate=stats.packets_per_second(now),
                        hex_bytes=hex_bytes,
                    ),
                    file=output,
                    flush=True,
                )
                last_display = now
            last_payload = payload
            last_sender = sender
    except KeyboardInterrupt:
        print("\nCtrl+C received; stopping cleanly.", file=output)
    finally:
        sock.close()
        if capture is not None:
            capture.close()
        print(final_summary(stats, monotonic_clock()), file=output, flush=True)
    return stats


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and optionally capture raw FH6 Data Out UDP packets."
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"UDP bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=port_number, default=DEFAULT_PORT, help=f"UDP port (default: {DEFAULT_PORT})")
    parser.add_argument("--capture", type=Path, help="write a versioned .fh6cap JSONL capture")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing capture file")
    parser.add_argument("--hex-bytes", type=nonnegative_int, default=DEFAULT_HEX_BYTES, help=f"payload bytes shown in hex (default: {DEFAULT_HEX_BYTES})")
    parser.add_argument("--stop-timeout", type=positive_float, default=DEFAULT_STOP_TIMEOUT, help=f"seconds of silence before a warning (default: {DEFAULT_STOP_TIMEOUT})")
    parser.add_argument("--verbose", action="store_true", help="print every packet instead of a one-second sample")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        run_probe(
            host=args.host,
            port=args.port,
            capture_path=args.capture,
            overwrite=args.overwrite,
            hex_bytes=args.hex_bytes,
            stop_timeout=args.stop_timeout,
            verbose=args.verbose,
        )
    except FileExistsError:
        print(
            f"ERROR: capture already exists: {args.capture}\n"
            "Choose a new filename or pass --overwrite.",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"ERROR: could not start UDP probe: {exc}", file=sys.stderr)
        if getattr(exc, "winerror", None) == 10048:
            print("Another process is already using that UDP port.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
