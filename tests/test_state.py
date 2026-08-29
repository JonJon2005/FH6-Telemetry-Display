from __future__ import annotations

import json
import struct

from app.config import Settings
from app.telemetry.parser import FH6_PACKET_SIZE
from app.telemetry.state import TelemetryState
from tests.test_validation import valid_packet


def test_valid_datagram_populates_live_snapshot() -> None:
    state = TelemetryState(Settings(telemetry_timeout_seconds=2))
    state.listener_ready("0.0.0.0", 20440)
    state.handle_datagram(bytes(valid_packet()), ("192.168.1.142", 5200), now=10)
    snapshot = state.snapshot(now=10.1)
    assert snapshot["connection"]["connected"] is True
    assert snapshot["connection"]["sender"] == "192.168.1.142:5200"
    assert snapshot["parser"]["latest_recognized"] is True
    assert len(snapshot["fields"]) == 89
    assert snapshot["telemetry"]["inputs"]["gear"]["label"] == "3"


def test_unrecognized_packet_is_counted_without_crashing() -> None:
    state = TelemetryState(Settings())
    state.handle_datagram(b"not FH6", ("127.0.0.1", 4000), now=1)
    snapshot = state.snapshot(now=1.1)
    assert snapshot["connection"]["traffic_active"] is True
    assert snapshot["connection"]["connected"] is False
    assert snapshot["parser"]["unknown_packets"] == 1
    assert "not the supported" in snapshot["guidance"]


def test_connection_turns_stale_after_timeout() -> None:
    state = TelemetryState(Settings(telemetry_timeout_seconds=2))
    state.handle_datagram(bytes(valid_packet()), ("127.0.0.1", 4000), now=5)
    assert state.snapshot(now=8)["connection"]["connected"] is False


def test_nonfinite_wire_float_remains_strict_json_safe() -> None:
    packet = valid_packet()
    struct.pack_into("<f", packet, 256, float("nan"))
    state = TelemetryState(Settings())
    state.handle_datagram(bytes(packet), ("127.0.0.1", 4000), now=1)
    json.dumps(state.snapshot(now=1), allow_nan=False)


def test_realtime_contract_is_normalized_and_excludes_debug_bulk() -> None:
    state = TelemetryState(Settings())
    state.handle_datagram(bytes(valid_packet()), ("127.0.0.1", 4000), now=1)
    realtime = state.realtime_snapshot(now=1.1)
    assert realtime["schema"] == "fh6-telemetry-state"
    assert realtime["schema_version"] == 1
    assert realtime["sequence"] == 1
    assert realtime["telemetry"]["vehicle"]["speed"]["miles_per_hour"] > 0
    assert "fields" not in realtime
    assert "raw_hex" not in realtime
    assert "parser" not in realtime


def test_debug_rows_remain_valid_when_bad_packet_follows_good_packet() -> None:
    state = TelemetryState(Settings())
    state.handle_datagram(bytes(valid_packet()), ("127.0.0.1", 4000), now=1)
    state.handle_datagram(b"bad", ("127.0.0.1", 4000), now=1.1)
    snapshot = state.snapshot(now=1.2)
    assert len(snapshot["fields"]) == 89
    assert snapshot["raw_hex"].startswith("0000  62 61 64")
    assert snapshot["parser"]["latest_recognized"] is False
    assert "latest packet is not" in snapshot["guidance"]
