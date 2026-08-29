from __future__ import annotations

import json
import math
from pathlib import Path
import struct

import pytest

from app.telemetry.parser import (
    FIELD_DEFINITIONS,
    FH6_PACKET_SIZE,
    PacketLengthError,
    decode_fields,
    parse_packet,
)
from tools.replay_capture import CaptureReader


def put(packet: bytearray, offset: int, binary_format: str, value: int | float) -> None:
    struct.pack_into("<" + binary_format, packet, offset, value)


def test_field_table_is_contiguous_and_covers_exact_packet_size() -> None:
    expected_offset = 0
    names: set[str] = set()
    for definition in FIELD_DEFINITIONS:
        assert definition.offset == expected_offset
        assert definition.name not in names
        names.add(definition.name)
        expected_offset += definition.size
    assert expected_offset == FH6_PACKET_SIZE
    assert len(FIELD_DEFINITIONS) == 89


def test_verified_anchor_offsets_and_types_are_pinned() -> None:
    by_name = {definition.name: definition for definition in FIELD_DEFINITIONS}
    anchors = {
        "IsRaceOn": (0, "S32"),
        "TimestampMS": (4, "U32"),
        "CarOrdinal": (212, "S32"),
        "CarGroup": (232, "U32"),
        "PositionX": (244, "F32"),
        "Speed": (256, "F32"),
        "TireTempFrontLeft": (268, "F32"),
        "LapNumber": (312, "U16"),
        "Accel": (315, "U8"),
        "Gear": (319, "U8"),
        "Steer": (320, "S8"),
        "ReservedTrailingByte": (323, "U8"),
    }
    assert {name: (by_name[name].offset, by_name[name].binary_type) for name in anchors} == anchors


@pytest.mark.parametrize("length", [0, 232, 311, 323, 325, 331])
def test_parser_rejects_every_unrecognized_length(length: int) -> None:
    with pytest.raises(PacketLengthError, match=f"length {length}"):
        parse_packet(bytes(length))


def test_parser_decodes_signed_unsigned_and_normalized_values() -> None:
    packet = bytearray(FH6_PACKET_SIZE)
    put(packet, 0, "i", 1)
    put(packet, 4, "I", 4_000_000_000)
    put(packet, 8, "f", 9000.0)
    put(packet, 12, "f", 900.0)
    put(packet, 16, "f", 4500.0)
    put(packet, 32, "f", 3.0)
    put(packet, 36, "f", 4.0)
    put(packet, 40, "f", 12.0)
    put(packet, 56, "f", math.pi / 2)
    put(packet, 212, "i", -123)
    put(packet, 216, "i", 4)
    put(packet, 220, "i", 800)
    put(packet, 224, "i", 2)
    put(packet, 228, "i", 5)
    put(packet, 232, "I", 4_000_000_001)
    put(packet, 256, "f", 10.0)
    put(packet, 260, "f", 74569.984375)
    put(packet, 264, "f", 100.0)
    for offset in (268, 272, 276, 280):
        put(packet, offset, "f", 212.0)
    put(packet, 284, "f", 10.0)
    put(packet, 288, "f", 0.5)
    put(packet, 292, "f", 1609.344)
    put(packet, 312, "H", 65530)
    put(packet, 314, "B", 7)
    put(packet, 315, "B", 255)
    put(packet, 316, "B", 128)
    put(packet, 317, "B", 64)
    put(packet, 318, "B", 1)
    put(packet, 319, "B", 2)
    put(packet, 320, "b", -127)
    put(packet, 321, "b", -10)
    put(packet, 322, "b", 12)
    put(packet, 323, "B", 99)

    parsed = parse_packet(bytes(packet))

    assert parsed.race.is_race_on
    assert parsed.race.timestamp_ms == 4_000_000_000
    assert parsed.race.timestamp_seconds == 4_000_000.0
    assert parsed.vehicle.car_ordinal == -123
    assert parsed.vehicle.car_group == 4_000_000_001
    assert parsed.vehicle.drivetrain.label == "AWD"
    assert parsed.vehicle.engine_rpm_percent == pytest.approx(50.0)
    assert parsed.vehicle.speed.kilometers_per_hour == pytest.approx(36.0)
    assert parsed.vehicle.speed.miles_per_hour == pytest.approx(22.3693629)
    assert parsed.vehicle.power.mechanical_horsepower == pytest.approx(100.0, rel=1e-5)
    assert parsed.vehicle.torque.pound_feet == pytest.approx(73.7562149)
    assert parsed.vehicle.boost.kilopascals == pytest.approx(68.9475729)
    assert parsed.vehicle.fuel_percent == pytest.approx(50.0)
    assert parsed.vehicle.distance_traveled.miles == pytest.approx(1.0)
    assert parsed.inputs.throttle.normalized == 1.0
    assert parsed.inputs.brake.normalized == pytest.approx(128 / 255)
    assert parsed.inputs.steering.normalized == -1.0
    assert parsed.inputs.gear.label == "2"
    assert parsed.inputs.normalized_driving_line == pytest.approx(-10 / 127)
    assert parsed.inputs.normalized_ai_brake_difference == pytest.approx(12 / 127)
    assert parsed.motion.velocity_meters_per_second.magnitude() == pytest.approx(13.0)
    assert parsed.motion.orientation_degrees.x == pytest.approx(90.0)
    assert parsed.wheels.front_left.tire_temperature.celsius == pytest.approx(100.0)
    assert parsed.metadata.trailing_reserved_byte == 99


def test_all_four_wheel_offsets_are_kept_independent() -> None:
    packet = bytearray(FH6_PACKET_SIZE)
    for index, offset in enumerate((68, 72, 76, 80), start=1):
        put(packet, offset, "f", index / 10)
    for index, offset in enumerate((100, 104, 108, 112), start=1):
        put(packet, offset, "f", float(index))
    for index, offset in enumerate((268, 272, 276, 280), start=1):
        put(packet, offset, "f", 100.0 + index)

    wheels = parse_packet(bytes(packet)).wheels
    assert [
        wheels.front_left.normalized_suspension_travel,
        wheels.front_right.normalized_suspension_travel,
        wheels.rear_left.normalized_suspension_travel,
        wheels.rear_right.normalized_suspension_travel,
    ] == pytest.approx([0.1, 0.2, 0.3, 0.4])
    assert [
        wheels.front_left.rotation_speed_radians_per_second,
        wheels.front_right.rotation_speed_radians_per_second,
        wheels.rear_left.rotation_speed_radians_per_second,
        wheels.rear_right.rotation_speed_radians_per_second,
    ] == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert [
        wheels.front_left.tire_temperature.source_fahrenheit,
        wheels.front_right.tire_temperature.source_fahrenheit,
        wheels.rear_left.tire_temperature.source_fahrenheit,
        wheels.rear_right.tire_temperature.source_fahrenheit,
    ] == pytest.approx([101.0, 102.0, 103.0, 104.0])


def test_puddle_bytes_preserve_both_conflicting_interpretations() -> None:
    packet = bytearray(FH6_PACKET_SIZE)
    put(packet, 132, "f", 0.5)

    puddle = parse_packet(bytes(packet)).wheels.front_left.puddle
    assert puddle.raw_hex == "0000003f"
    assert puddle.as_float32_depth == pytest.approx(0.5)
    assert puddle.as_signed_int32 == 1_056_964_608
    assert puddle.interpretation.startswith("unresolved")


def test_unverified_gear_code_is_not_given_an_invented_meaning() -> None:
    packet = bytearray(FH6_PACKET_SIZE)
    packet[319] = 11
    gear = parse_packet(bytes(packet)).inputs.gear
    assert gear.raw == 11
    assert gear.label == "unknown(11)"
    assert gear.is_unverified_shift_state


def test_packet_model_converts_to_json_ready_nested_dictionary() -> None:
    parsed = parse_packet(bytes(FH6_PACKET_SIZE))
    encoded = json.dumps(parsed.to_dict(), allow_nan=False)
    assert '"parser_version": "fh6-324-v1"' in encoded
    assert '"raw_hex": "00000000"' in encoded


def test_decode_fields_exposes_every_raw_wire_value() -> None:
    values = decode_fields(bytes(FH6_PACKET_SIZE))
    assert len(values) == len(FIELD_DEFINITIONS)
    assert values["IsRaceOn"] == 0
    assert values["WheelInPuddleFrontLeft"] == b"\x00\x00\x00\x00"
    assert values["ReservedTrailingByte"] == 0


LOCAL_CAPTURE = Path(__file__).parents[1] / "captures" / "first-drive.fh6cap"


@pytest.mark.skipif(not LOCAL_CAPTURE.exists(), reason="local user capture is not present")
def test_every_packet_in_local_capture_decodes_and_matches_speed_vector() -> None:
    packet_count = 0
    maximum_error = 0.0
    with CaptureReader(LOCAL_CAPTURE) as capture:
        for captured in capture:
            parsed = parse_packet(captured.payload)
            packet_count += 1
            maximum_error = max(
                maximum_error,
                abs(
                    parsed.vehicle.speed.meters_per_second
                    - parsed.motion.velocity_meters_per_second.magnitude()
                ),
            )
    assert packet_count > 0
    assert maximum_error < 0.00001
