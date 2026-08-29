from __future__ import annotations

import struct

from app.telemetry.diagnostics import diagnostic_rows
from app.telemetry.parser import FH6_PACKET_SIZE, parse_packet
from app.telemetry.validation import validate_telemetry


def put(packet: bytearray, offset: int, binary_format: str, value: int | float) -> None:
    struct.pack_into("<" + binary_format, packet, offset, value)


def valid_packet() -> bytearray:
    packet = bytearray(FH6_PACKET_SIZE)
    put(packet, 0, "i", 1)
    put(packet, 8, "f", 8000)
    put(packet, 12, "f", 800)
    put(packet, 16, "f", 4000)
    put(packet, 40, "f", 20)
    for offset in (68, 72, 76, 80):
        put(packet, offset, "f", 0.5)
    put(packet, 216, "i", 4)
    put(packet, 224, "i", 2)
    put(packet, 228, "i", 8)
    put(packet, 256, "f", 20)
    for offset in (268, 272, 276, 280):
        put(packet, offset, "f", 180)
    put(packet, 288, "f", 0.75)
    packet[319] = 3
    return packet


def test_valid_packet_passes_layout_sanity_checks() -> None:
    result = validate_telemetry(parse_packet(bytes(valid_packet())))
    assert result.layout_likely_valid
    assert result.important_failures == 0
    assert result.checks_passed >= 20


def test_multiple_important_failures_flag_probably_wrong_layout() -> None:
    packet = valid_packet()
    put(packet, 0, "i", 9)
    put(packet, 8, "f", -500)
    put(packet, 216, "i", 99)
    put(packet, 256, "f", 500)
    put(packet, 288, "f", 3)
    result = validate_telemetry(parse_packet(bytes(packet)))
    assert not result.layout_likely_valid
    assert result.important_failures >= 3
    assert result.issues[0].field == "layout"


def test_unverified_gear_11_is_visible_without_invalidating_layout() -> None:
    packet = valid_packet()
    packet[319] = 11
    result = validate_telemetry(parse_packet(bytes(packet)))
    assert result.layout_likely_valid
    assert any(issue.field == "Gear" and issue.severity == "info" for issue in result.issues)


def test_diagnostic_rows_show_every_wire_field_and_normalization() -> None:
    packet = bytes(valid_packet())
    rows = diagnostic_rows(packet, parse_packet(packet))
    by_name = {row["name"]: row for row in rows}
    assert len(rows) == 89
    assert "mph" in by_name["Speed"]["decoded_value"]
    assert by_name["Speed"]["offset"] == 256
    assert by_name["Speed"]["binary_type"] == "F32"
    assert "S32" in by_name["WheelInPuddleFrontLeft"]["decoded_value"]
