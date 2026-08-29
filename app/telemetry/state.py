"""In-memory state shared by the UDP receiver and web diagnostics."""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
import math
import time

from app.config import Settings
from .diagnostics import diagnostic_rows
from .parser import FORMAT_NAME, PARSER_VERSION, FH6_PACKET_SIZE, parse_packet
from .validation import ValidationResult, validate_telemetry
from .models import TelemetryPacket


class TelemetryState:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.listener_status = "starting"
        self.listener_error: str | None = None
        self.bound_address = f"{settings.udp_host}:{settings.udp_port}"
        self.total_packets = 0
        self.total_bytes = 0
        self.unknown_packet_count = 0
        self.parse_error_count = 0
        self.packet_sizes: Counter[int] = Counter()
        self.last_sender: tuple[str, int] | None = None
        self.last_received_at: str | None = None
        self.last_received_monotonic: float | None = None
        self.last_good_monotonic: float | None = None
        self.recent_packets: deque[float] = deque()
        self.latest_payload: bytes | None = None
        self.latest_valid_payload: bytes | None = None
        self.latest_packet: TelemetryPacket | None = None
        self.latest_rows: list[dict[str, object]] = []
        self._rows_revision = -1
        self.latest_validation: ValidationResult | None = None
        self.latest_error: str | None = None
        self.latest_recognized = False
        self.valid_packet_count = 0
        self.revision = 0

    def listener_ready(self, host: str, port: int) -> None:
        self.listener_status = "listening"
        self.bound_address = f"{host}:{port}"
        self.listener_error = None

    def listener_failed(self, error: BaseException) -> None:
        self.listener_status = "error"
        self.listener_error = str(error)

    def handle_datagram(self, data: bytes, address: tuple[str, int], *, now: float | None = None) -> TelemetryPacket | None:
        # Count every packet, but only replace live data after a valid parse.
        current = time.monotonic() if now is None else now
        self.total_packets += 1
        self.total_bytes += len(data)
        self.packet_sizes[len(data)] += 1
        self.last_sender = address
        self.last_received_at = datetime.now(timezone.utc).isoformat()
        self.last_received_monotonic = current
        self.recent_packets.append(current)
        self._prune(current)
        self.latest_payload = bytes(data)
        self.latest_recognized = False

        if len(data) != FH6_PACKET_SIZE:
            # Unknown packets are counted without crashing the app.
            self.unknown_packet_count += 1
            self.latest_error = f"unrecognized packet length {len(data)}; expected {FH6_PACKET_SIZE}"
            return None
        try:
            packet = parse_packet(data)
            validation = validate_telemetry(packet)
            self.latest_packet = packet
            self.latest_valid_payload = bytes(data)
            self.latest_validation = validation
            self.last_good_monotonic = current
            self.latest_recognized = True
            self.latest_error = None
            self.valid_packet_count += 1
            self.revision += 1
            return packet
        except (ValueError, OverflowError) as error:
            self.parse_error_count += 1
            self.latest_error = str(error)
            return None

    def snapshot(self, *, now: float | None = None) -> dict[str, object]:
        # The debug page gets extra raw and validation details.
        current, connection = self._connection_snapshot(now)
        traffic_active = bool(connection["traffic_active"])
        connected = bool(connection["connected"])
        issues = self.latest_validation.to_dict() if self.latest_validation else None
        issue_fields = sorted({issue.field for issue in self.latest_validation.issues}) if self.latest_validation else []
        if self.latest_packet is not None and self.latest_valid_payload is not None and self._rows_revision != self.revision:
            self.latest_rows = diagnostic_rows(self.latest_valid_payload, self.latest_packet)
            self._rows_revision = self.revision
        snapshot = {
            "listener": {"status": self.listener_status, "bind": self.bound_address, "error": self.listener_error},
            "connection": connection,
            "parser": {
                "format": FORMAT_NAME,
                "version": PARSER_VERSION,
                "latest_recognized": self.latest_recognized,
                "unknown_packets": self.unknown_packet_count,
                "parse_errors": self.parse_error_count,
                "latest_error": self.latest_error,
                "validation": issues,
                "issue_fields": issue_fields,
            },
            "telemetry": self.latest_packet.to_dict() if self.latest_packet else None,
            "fields": self.latest_rows,
            "raw_hex": _hex_dump(self.latest_payload) if self.latest_payload is not None else "",
            "guidance": self._guidance(traffic_active, connected),
        }
        return _json_safe(snapshot)

    def realtime_snapshot(self, *, now: float | None = None) -> dict[str, object]:
        """Return the compact normalized contract broadcast to dashboards."""
        # Keep normal dashboard messages small and quick to send.
        _, connection = self._connection_snapshot(now)
        return _json_safe({
            "schema": "fh6-telemetry-state",
            "schema_version": 1,
            "sequence": self.revision,
            "connection": connection,
            "telemetry": self.latest_packet.to_dict() if self.latest_packet else None,
        })

    def _connection_snapshot(self, now: float | None) -> tuple[float, dict[str, object]]:
        current = time.monotonic() if now is None else now
        self._prune(current)
        traffic_active = self.last_received_monotonic is not None and current - self.last_received_monotonic <= self.settings.telemetry_timeout_seconds
        connected = self.last_good_monotonic is not None and current - self.last_good_monotonic <= self.settings.telemetry_timeout_seconds
        span = current - self.recent_packets[0] if len(self.recent_packets) > 1 else 0
        packets_per_second = (len(self.recent_packets) - 1) / span if span > 0 else (1.0 if self.recent_packets else 0.0)
        return current, {
            "connected": connected,
            "traffic_active": traffic_active,
            "packets_per_second": round(packets_per_second, 2),
            "total_packets": self.total_packets,
            "valid_packets": self.valid_packet_count,
            "total_bytes": self.total_bytes,
            "last_received_at": self.last_received_at,
            "sender": f"{self.last_sender[0]}:{self.last_sender[1]}" if self.last_sender else None,
            "latest_packet_size": len(self.latest_payload) if self.latest_payload is not None else None,
            "packet_sizes": dict(sorted(self.packet_sizes.items())),
        }

    def _prune(self, now: float) -> None:
        # Two seconds is enough for the live packet-rate estimate.
        cutoff = now - 2.0
        while self.recent_packets and self.recent_packets[0] < cutoff:
            self.recent_packets.popleft()

    def _guidance(self, traffic_active: bool, connected: bool) -> str:
        if self.listener_status == "error":
            return "UDP listener failed. Close any probe already using the port, then restart this service."
        if not self.total_packets:
            return "Waiting for telemetry. In FH6, set Data Out IP Address to this PC's LAN IPv4 address and port 20440."
        if traffic_active and not self.latest_recognized:
            return "UDP traffic is arriving, but the latest packet is not the supported 324-byte FH6 layout."
        if not traffic_active:
            return "Telemetry stopped. Start or resume driving; FH6 may pause Data Out in menus."
        if self.latest_validation and not self.latest_validation.layout_likely_valid:
            return "Packets are arriving, but several sanity checks failed. The selected packet layout is probably incorrect."
        return "Live FH6 telemetry is decoding normally. Exercise throttle, brake, steering, gears, and RPM to validate movement."


def _hex_dump(data: bytes) -> str:
    lines: list[str] = []
    for offset in range(0, len(data), 16):
        chunk = data[offset:offset + 16]
        hexes = " ".join(f"{byte:02x}" for byte in chunk)
        ascii_text = "".join(chr(byte) if 32 <= byte < 127 else "." for byte in chunk)
        lines.append(f"{offset:04x}  {hexes:<47}  {ascii_text}")
    return "\n".join(lines)


def _json_safe(value: object) -> object:
    """Replace non-finite wire floats before strict JSON serialization."""
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
