"""Strict parser for the verified 324-byte FH6 Data Out packet."""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Final

from .models import (
    Distance,
    DriverInputs,
    Drivetrain,
    Gear,
    MotionTelemetry,
    PacketMetadata,
    PositionTelemetry,
    Power,
    Pressure,
    PuddleReading,
    RaceTelemetry,
    RatioInput,
    Speed,
    SteeringInput,
    TelemetryPacket,
    Temperature,
    Torque,
    Vector3,
    VehicleTelemetry,
    WheelTelemetry,
    WheelsTelemetry,
)


FH6_PACKET_SIZE: Final = 324
FORMAT_NAME: Final = "FH6 Horizon Data Out 324-byte"
PARSER_VERSION: Final = "fh6-324-v1"


class TelemetryParseError(ValueError):
    """Base class for safe telemetry decode failures."""


class PacketLengthError(TelemetryParseError):
    def __init__(self, actual: int, expected: int = FH6_PACKET_SIZE) -> None:
        super().__init__(f"unrecognized FH6 packet length {actual}; expected exactly {expected} bytes")
        self.actual = actual
        self.expected = expected


@dataclass(frozen=True, slots=True)
class FieldDefinition:
    name: str
    offset: int
    binary_type: str
    size: int
    source_unit: str
    normalized_unit: str
    confidence: str = "CONFIRMED"
    notes: str = ""


def _field(
    name: str,
    offset: int,
    binary_type: str,
    source_unit: str,
    normalized_unit: str = "same as source",
    *,
    confidence: str = "CONFIRMED",
    notes: str = "",
) -> FieldDefinition:
    sizes = {"S32": 4, "U32": 4, "F32": 4, "U16": 2, "U8": 1, "S8": 1, "S32/F32": 4}
    return FieldDefinition(
        name, offset, binary_type, sizes[binary_type], source_unit, normalized_unit, confidence, notes
    )


FIELD_DEFINITIONS: Final[tuple[FieldDefinition, ...]] = (
    # This table maps every byte in the FH6 packet.
    _field("IsRaceOn", 0, "S32", "0/1 active-driving flag", "raw integer + boolean"),
    _field("TimestampMS", 4, "U32", "milliseconds", "milliseconds + seconds"),
    _field("EngineMaxRpm", 8, "F32", "rpm"),
    _field("EngineIdleRpm", 12, "F32", "rpm"),
    _field("CurrentEngineRpm", 16, "F32", "rpm"),
    _field("AccelerationX", 20, "F32", "unverified; likely m/s²", confidence="LIKELY"),
    _field("AccelerationY", 24, "F32", "unverified; likely m/s²", confidence="LIKELY"),
    _field("AccelerationZ", 28, "F32", "unverified; likely m/s²", confidence="LIKELY"),
    _field("VelocityX", 32, "F32", "m/s", notes="local right axis"),
    _field("VelocityY", 36, "F32", "m/s", notes="local up axis"),
    _field("VelocityZ", 40, "F32", "m/s", notes="local forward axis"),
    _field("AngularVelocityX", 44, "F32", "rad/s", "rad/s + deg/s", notes="local pitch"),
    _field("AngularVelocityY", 48, "F32", "rad/s", "rad/s + deg/s", notes="local yaw"),
    _field("AngularVelocityZ", 52, "F32", "rad/s", "rad/s + deg/s", notes="local roll"),
    _field("Yaw", 56, "F32", "radians", "radians + degrees"),
    _field("Pitch", 60, "F32", "radians", "radians + degrees"),
    _field("Roll", 64, "F32", "radians", "radians + degrees"),
    _field("NormalizedSuspensionTravelFrontLeft", 68, "F32", "0 max stretch to 1 max compression"),
    _field("NormalizedSuspensionTravelFrontRight", 72, "F32", "0 max stretch to 1 max compression"),
    _field("NormalizedSuspensionTravelRearLeft", 76, "F32", "0 max stretch to 1 max compression"),
    _field("NormalizedSuspensionTravelRearRight", 80, "F32", "0 max stretch to 1 max compression"),
    _field("TireSlipRatioFrontLeft", 84, "F32", "normalized slip ratio"),
    _field("TireSlipRatioFrontRight", 88, "F32", "normalized slip ratio"),
    _field("TireSlipRatioRearLeft", 92, "F32", "normalized slip ratio"),
    _field("TireSlipRatioRearRight", 96, "F32", "normalized slip ratio"),
    _field("WheelRotationSpeedFrontLeft", 100, "F32", "rad/s", "rad/s + rpm"),
    _field("WheelRotationSpeedFrontRight", 104, "F32", "rad/s", "rad/s + rpm"),
    _field("WheelRotationSpeedRearLeft", 108, "F32", "rad/s", "rad/s + rpm"),
    _field("WheelRotationSpeedRearRight", 112, "F32", "rad/s", "rad/s + rpm"),
    _field("WheelOnRumbleStripFrontLeft", 116, "S32", "0/1 flag", "raw integer + boolean"),
    _field("WheelOnRumbleStripFrontRight", 120, "S32", "0/1 flag", "raw integer + boolean"),
    _field("WheelOnRumbleStripRearLeft", 124, "S32", "0/1 flag", "raw integer + boolean"),
    _field("WheelOnRumbleStripRearRight", 128, "S32", "0/1 flag", "raw integer + boolean"),
    _field("WheelInPuddleFrontLeft", 132, "S32/F32", "official flag vs historical depth", "both interpretations preserved", confidence="UNVERIFIED"),
    _field("WheelInPuddleFrontRight", 136, "S32/F32", "official flag vs historical depth", "both interpretations preserved", confidence="UNVERIFIED"),
    _field("WheelInPuddleRearLeft", 140, "S32/F32", "official flag vs historical depth", "both interpretations preserved", confidence="UNVERIFIED"),
    _field("WheelInPuddleRearRight", 144, "S32/F32", "official flag vs historical depth", "both interpretations preserved", confidence="UNVERIFIED"),
    _field("SurfaceRumbleFrontLeft", 148, "F32", "non-dimensional"),
    _field("SurfaceRumbleFrontRight", 152, "F32", "non-dimensional"),
    _field("SurfaceRumbleRearLeft", 156, "F32", "non-dimensional"),
    _field("SurfaceRumbleRearRight", 160, "F32", "non-dimensional"),
    _field("TireSlipAngleFrontLeft", 164, "F32", "normalized slip angle"),
    _field("TireSlipAngleFrontRight", 168, "F32", "normalized slip angle"),
    _field("TireSlipAngleRearLeft", 172, "F32", "normalized slip angle"),
    _field("TireSlipAngleRearRight", 176, "F32", "normalized slip angle"),
    _field("TireCombinedSlipFrontLeft", 180, "F32", "normalized combined slip"),
    _field("TireCombinedSlipFrontRight", 184, "F32", "normalized combined slip"),
    _field("TireCombinedSlipRearLeft", 188, "F32", "normalized combined slip"),
    _field("TireCombinedSlipRearRight", 192, "F32", "normalized combined slip"),
    _field("SuspensionTravelMetersFrontLeft", 196, "F32", "meters"),
    _field("SuspensionTravelMetersFrontRight", 200, "F32", "meters"),
    _field("SuspensionTravelMetersRearLeft", 204, "F32", "meters"),
    _field("SuspensionTravelMetersRearRight", 208, "F32", "meters"),
    _field("CarOrdinal", 212, "S32", "identifier"),
    _field("CarClass", 216, "S32", "class code 0–7"),
    _field("CarPerformanceIndex", 220, "S32", "performance index"),
    _field("DrivetrainType", 224, "S32", "0 FWD, 1 RWD, 2 AWD", "raw code + label"),
    _field("NumCylinders", 228, "S32", "count"),
    _field("CarGroup", 232, "U32", "identifier"),
    _field("SmashableVelDiff", 236, "F32", "m/s"),
    _field("SmashableMass", 240, "F32", "kg"),
    _field("PositionX", 244, "F32", "world meters"),
    _field("PositionY", 248, "F32", "world meters"),
    _field("PositionZ", 252, "F32", "world meters"),
    _field("Speed", 256, "F32", "m/s", "m/s + km/h + mph"),
    _field("Power", 260, "F32", "watts", "watts + kW + mechanical hp"),
    _field("Torque", 264, "F32", "N·m", "N·m + lb-ft"),
    _field("TireTempFrontLeft", 268, "F32", "°F", "°F + °C"),
    _field("TireTempFrontRight", 272, "F32", "°F", "°F + °C"),
    _field("TireTempRearLeft", 276, "F32", "°F", "°F + °C"),
    _field("TireTempRearRight", 280, "F32", "°F", "°F + °C"),
    _field("Boost", 284, "F32", "psi above atmosphere", "psi + kPa"),
    _field("Fuel", 288, "F32", "0–1 fraction", "fraction + percent"),
    _field("DistanceTraveled", 292, "F32", "meters", "meters + km + miles"),
    _field("BestLap", 296, "F32", "seconds"),
    _field("LastLap", 300, "F32", "seconds"),
    _field("CurrentLap", 304, "F32", "seconds"),
    _field("CurrentRaceTime", 308, "F32", "seconds"),
    _field("LapNumber", 312, "U16", "completed-lap count"),
    _field("RacePosition", 314, "U8", "position"),
    _field("Accel", 315, "U8", "0–255", "raw + 0–1 + percent"),
    _field("Brake", 316, "U8", "0–255", "raw + 0–1 + percent"),
    _field("Clutch", 317, "U8", "0–255", "raw + 0–1 + percent"),
    _field("HandBrake", 318, "U8", "0–255", "raw + 0–1 + percent"),
    _field("Gear", 319, "U8", "gear code", "raw code + conservative label", confidence="PARTIAL"),
    _field("Steer", 320, "S8", "−127–127", "raw + −1–1 + signed percent"),
    _field("NormalizedDrivingLine", 321, "S8", "−127–127"),
    _field("NormalizedAIBrakeDifference", 322, "S8", "−127–127"),
    _field("ReservedTrailingByte", 323, "U8", "reserved", confidence="LIKELY", notes="zero in first 410 local packets"),
)


_STRUCTS: Final = {
    "S32": struct.Struct("<i"),
    "U32": struct.Struct("<I"),
    "F32": struct.Struct("<f"),
    "U16": struct.Struct("<H"),
    "U8": struct.Struct("<B"),
    "S8": struct.Struct("<b"),
}


def _assert_field_layout() -> None:
    # Catch a missing or overlapping field when the app starts.
    expected_offset = 0
    names: set[str] = set()
    for definition in FIELD_DEFINITIONS:
        if definition.name in names:
            raise RuntimeError(f"duplicate field name: {definition.name}")
        names.add(definition.name)
        if definition.offset != expected_offset:
            raise RuntimeError(
                f"field layout gap/overlap before {definition.name}: "
                f"expected {expected_offset}, got {definition.offset}"
            )
        expected_offset += definition.size
    if expected_offset != FH6_PACKET_SIZE:
        raise RuntimeError(f"field table covers {expected_offset}, expected {FH6_PACKET_SIZE}")


_assert_field_layout()


def decode_fields(data: bytes) -> dict[str, int | float | bytes]:
    """Decode every wire field without applying normalization."""
    if len(data) != FH6_PACKET_SIZE:
        raise PacketLengthError(len(data))
    values: dict[str, int | float | bytes] = {}
    for definition in FIELD_DEFINITIONS:
        if definition.binary_type == "S32/F32":
            # Keep the disputed puddle bytes untouched for both meanings.
            values[definition.name] = data[definition.offset : definition.offset + 4]
        else:
            values[definition.name] = _STRUCTS[definition.binary_type].unpack_from(
                data, definition.offset
            )[0]
    return values


def parse_packet(data: bytes) -> TelemetryPacket:
    """Parse exactly one FH6 packet into immutable nested telemetry data."""
    values = decode_fields(data)

    def integer(name: str) -> int:
        value = values[name]
        assert isinstance(value, int)
        return value

    def floating(name: str) -> float:
        value = values[name]
        assert isinstance(value, float)
        return value

    def raw_bytes(name: str) -> bytes:
        value = values[name]
        assert isinstance(value, bytes)
        return value

    radians_to_degrees = 180.0 / math.pi
    # Convert here so every dashboard uses the same units.
    angular_radians = Vector3(
        floating("AngularVelocityX"),
        floating("AngularVelocityY"),
        floating("AngularVelocityZ"),
    )
    orientation_radians = Vector3(
        floating("Yaw"), floating("Pitch"), floating("Roll")
    )

    def wheel(corner: str) -> WheelTelemetry:
        # All four wheels share this layout with a different name ending.
        rotation_rad_s = floating(f"WheelRotationSpeed{corner}")
        raw_rumble = integer(f"WheelOnRumbleStrip{corner}")
        return WheelTelemetry(
            normalized_suspension_travel=floating(f"NormalizedSuspensionTravel{corner}"),
            tire_slip_ratio=floating(f"TireSlipRatio{corner}"),
            rotation_speed_radians_per_second=rotation_rad_s,
            rotation_speed_rpm=rotation_rad_s * 60.0 / (2.0 * math.pi),
            raw_on_rumble_strip=raw_rumble,
            on_rumble_strip=raw_rumble != 0,
            puddle=PuddleReading.from_wire_bytes(raw_bytes(f"WheelInPuddle{corner}")),
            surface_rumble=floating(f"SurfaceRumble{corner}"),
            tire_slip_angle=floating(f"TireSlipAngle{corner}"),
            tire_combined_slip=floating(f"TireCombinedSlip{corner}"),
            suspension_travel_meters=floating(f"SuspensionTravelMeters{corner}"),
            tire_temperature=Temperature.from_fahrenheit(floating(f"TireTemp{corner}")),
        )

    fuel = floating("Fuel")
    raw_is_race_on = integer("IsRaceOn")
    timestamp_ms = integer("TimestampMS")
    maximum_rpm = floating("EngineMaxRpm")
    current_rpm = floating("CurrentEngineRpm")
    rpm_fraction = current_rpm / maximum_rpm if maximum_rpm > 0 else 0.0
    driving_line_raw = integer("NormalizedDrivingLine")
    ai_brake_raw = integer("NormalizedAIBrakeDifference")

    def normalized_s8(value: int) -> float:
        return max(-1.0, min(1.0, value / 127.0))

    return TelemetryPacket(
        metadata=PacketMetadata(
            format_name=FORMAT_NAME,
            parser_version=PARSER_VERSION,
            packet_size=len(data),
            trailing_reserved_byte=integer("ReservedTrailingByte"),
        ),
        race=RaceTelemetry(
            raw_is_race_on=raw_is_race_on,
            is_race_on=raw_is_race_on != 0,
            timestamp_ms=timestamp_ms,
            timestamp_seconds=timestamp_ms / 1000.0,
            best_lap_seconds=floating("BestLap"),
            last_lap_seconds=floating("LastLap"),
            current_lap_seconds=floating("CurrentLap"),
            current_race_time_seconds=floating("CurrentRaceTime"),
            lap_number=integer("LapNumber"),
            race_position=integer("RacePosition"),
        ),
        vehicle=VehicleTelemetry(
            engine_max_rpm=maximum_rpm,
            engine_idle_rpm=floating("EngineIdleRpm"),
            current_engine_rpm=current_rpm,
            engine_rpm_fraction=rpm_fraction,
            engine_rpm_percent=rpm_fraction * 100.0,
            car_ordinal=integer("CarOrdinal"),
            car_class=integer("CarClass"),
            performance_index=integer("CarPerformanceIndex"),
            drivetrain=Drivetrain.from_raw(integer("DrivetrainType")),
            cylinder_count=integer("NumCylinders"),
            car_group=integer("CarGroup"),
            smashable_velocity_difference_meters_per_second=floating("SmashableVelDiff"),
            smashable_mass_kg=floating("SmashableMass"),
            speed=Speed.from_meters_per_second(floating("Speed")),
            power=Power.from_watts(floating("Power")),
            torque=Torque.from_newton_meters(floating("Torque")),
            boost=Pressure.from_psi(floating("Boost")),
            fuel_fraction=fuel,
            fuel_percent=fuel * 100.0,
            distance_traveled=Distance.from_meters(floating("DistanceTraveled")),
        ),
        inputs=DriverInputs(
            throttle=RatioInput.from_u8(integer("Accel")),
            brake=RatioInput.from_u8(integer("Brake")),
            clutch=RatioInput.from_u8(integer("Clutch")),
            handbrake=RatioInput.from_u8(integer("HandBrake")),
            steering=SteeringInput.from_s8(integer("Steer")),
            gear=Gear.from_raw(integer("Gear")),
            normalized_driving_line_raw=driving_line_raw,
            normalized_driving_line=normalized_s8(driving_line_raw),
            normalized_ai_brake_difference_raw=ai_brake_raw,
            normalized_ai_brake_difference=normalized_s8(ai_brake_raw),
        ),
        motion=MotionTelemetry(
            acceleration_source=Vector3(
                floating("AccelerationX"),
                floating("AccelerationY"),
                floating("AccelerationZ"),
            ),
            acceleration_source_unit="unverified; likely meters per second squared",
            velocity_meters_per_second=Vector3(
                floating("VelocityX"), floating("VelocityY"), floating("VelocityZ")
            ),
            angular_velocity_radians_per_second=angular_radians,
            angular_velocity_degrees_per_second=angular_radians.scaled(radians_to_degrees),
            orientation_radians=orientation_radians,
            orientation_degrees=orientation_radians.scaled(radians_to_degrees),
        ),
        position=PositionTelemetry(
            world_meters=Vector3(
                floating("PositionX"), floating("PositionY"), floating("PositionZ")
            )
        ),
        wheels=WheelsTelemetry(
            front_left=wheel("FrontLeft"),
            front_right=wheel("FrontRight"),
            rear_left=wheel("RearLeft"),
            rear_right=wheel("RearRight"),
        ),
    )
