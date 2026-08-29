"""Strongly structured, unit-explicit FH6 telemetry models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import struct
from typing import Any


MPS_TO_KPH = 3.6
MPS_TO_MPH = 2.2369362920544
WATTS_PER_MECHANICAL_HP = 745.6998715822702
NM_TO_LB_FT = 0.737562149277
PSI_TO_KPA = 6.894757293168
METERS_PER_MILE = 1609.344


@dataclass(frozen=True, slots=True)
class Vector3:
    x: float
    y: float
    z: float

    def magnitude(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def scaled(self, factor: float) -> "Vector3":
        return Vector3(self.x * factor, self.y * factor, self.z * factor)


@dataclass(frozen=True, slots=True)
class Speed:
    meters_per_second: float
    kilometers_per_hour: float
    miles_per_hour: float

    @classmethod
    def from_meters_per_second(cls, value: float) -> "Speed":
        return cls(value, value * MPS_TO_KPH, value * MPS_TO_MPH)


@dataclass(frozen=True, slots=True)
class Temperature:
    source_fahrenheit: float
    celsius: float

    @classmethod
    def from_fahrenheit(cls, value: float) -> "Temperature":
        return cls(value, (value - 32.0) * 5.0 / 9.0)


@dataclass(frozen=True, slots=True)
class Power:
    source_watts: float
    kilowatts: float
    mechanical_horsepower: float

    @classmethod
    def from_watts(cls, value: float) -> "Power":
        return cls(value, value / 1000.0, value / WATTS_PER_MECHANICAL_HP)


@dataclass(frozen=True, slots=True)
class Torque:
    source_newton_meters: float
    pound_feet: float

    @classmethod
    def from_newton_meters(cls, value: float) -> "Torque":
        return cls(value, value * NM_TO_LB_FT)


@dataclass(frozen=True, slots=True)
class Pressure:
    source_psi: float
    kilopascals: float

    @classmethod
    def from_psi(cls, value: float) -> "Pressure":
        return cls(value, value * PSI_TO_KPA)


@dataclass(frozen=True, slots=True)
class Distance:
    source_meters: float
    kilometers: float
    miles: float

    @classmethod
    def from_meters(cls, value: float) -> "Distance":
        return cls(value, value / 1000.0, value / METERS_PER_MILE)


@dataclass(frozen=True, slots=True)
class RatioInput:
    raw: int
    normalized: float
    percent: float

    @classmethod
    def from_u8(cls, value: int) -> "RatioInput":
        # FH6 sends pedal inputs as a byte from 0 to 255.
        normalized = value / 255.0
        return cls(value, normalized, normalized * 100.0)


@dataclass(frozen=True, slots=True)
class SteeringInput:
    raw: int
    normalized: float
    percent: float

    @classmethod
    def from_s8(cls, value: int) -> "SteeringInput":
        # Left stays negative and right stays positive.
        normalized = max(-1.0, min(1.0, value / 127.0))
        return cls(value, normalized, normalized * 100.0)


@dataclass(frozen=True, slots=True)
class Gear:
    raw: int
    label: str
    is_forward_gear: bool
    is_unverified_shift_state: bool

    @classmethod
    def from_raw(cls, value: int) -> "Gear":
        if value == 0:
            return cls(value, "R", False, False)
        if 1 <= value <= 10:
            return cls(value, str(value), True, False)
        # Gear 11 showed up during shifts, but its meaning is still unknown.
        return cls(value, f"unknown({value})", False, value == 11)


@dataclass(frozen=True, slots=True)
class Drivetrain:
    raw: int
    label: str

    @classmethod
    def from_raw(cls, value: int) -> "Drivetrain":
        return cls(value, {0: "FWD", 1: "RWD", 2: "AWD"}.get(value, f"unknown({value})"))


@dataclass(frozen=True, slots=True)
class PuddleReading:
    """Preserve both interpretations of the unresolved 4-byte puddle field."""

    raw_hex: str
    as_signed_int32: int
    as_float32_depth: float
    interpretation: str = "unresolved: official S32 flag vs historical F32 depth"

    @classmethod
    def from_wire_bytes(cls, value: bytes) -> "PuddleReading":
        return cls(
            raw_hex=value.hex(),
            as_signed_int32=struct.unpack("<i", value)[0],
            as_float32_depth=struct.unpack("<f", value)[0],
        )


@dataclass(frozen=True, slots=True)
class RaceTelemetry:
    raw_is_race_on: int
    is_race_on: bool
    timestamp_ms: int
    timestamp_seconds: float
    best_lap_seconds: float
    last_lap_seconds: float
    current_lap_seconds: float
    current_race_time_seconds: float
    lap_number: int
    race_position: int


@dataclass(frozen=True, slots=True)
class VehicleTelemetry:
    engine_max_rpm: float
    engine_idle_rpm: float
    current_engine_rpm: float
    engine_rpm_fraction: float
    engine_rpm_percent: float
    car_ordinal: int
    car_class: int
    performance_index: int
    drivetrain: Drivetrain
    cylinder_count: int
    car_group: int
    smashable_velocity_difference_meters_per_second: float
    smashable_mass_kg: float
    speed: Speed
    power: Power
    torque: Torque
    boost: Pressure
    fuel_fraction: float
    fuel_percent: float
    distance_traveled: Distance


@dataclass(frozen=True, slots=True)
class MotionTelemetry:
    acceleration_source: Vector3
    acceleration_source_unit: str
    velocity_meters_per_second: Vector3
    angular_velocity_radians_per_second: Vector3
    angular_velocity_degrees_per_second: Vector3
    orientation_radians: Vector3
    orientation_degrees: Vector3


@dataclass(frozen=True, slots=True)
class PositionTelemetry:
    world_meters: Vector3


@dataclass(frozen=True, slots=True)
class DriverInputs:
    throttle: RatioInput
    brake: RatioInput
    clutch: RatioInput
    handbrake: RatioInput
    steering: SteeringInput
    gear: Gear
    normalized_driving_line_raw: int
    normalized_driving_line: float
    normalized_ai_brake_difference_raw: int
    normalized_ai_brake_difference: float


@dataclass(frozen=True, slots=True)
class WheelTelemetry:
    normalized_suspension_travel: float
    tire_slip_ratio: float
    rotation_speed_radians_per_second: float
    rotation_speed_rpm: float
    raw_on_rumble_strip: int
    on_rumble_strip: bool
    puddle: PuddleReading
    surface_rumble: float
    tire_slip_angle: float
    tire_combined_slip: float
    suspension_travel_meters: float
    tire_temperature: Temperature


@dataclass(frozen=True, slots=True)
class WheelsTelemetry:
    front_left: WheelTelemetry
    front_right: WheelTelemetry
    rear_left: WheelTelemetry
    rear_right: WheelTelemetry


@dataclass(frozen=True, slots=True)
class PacketMetadata:
    format_name: str
    parser_version: str
    packet_size: int
    trailing_reserved_byte: int


@dataclass(frozen=True, slots=True)
class TelemetryPacket:
    metadata: PacketMetadata
    race: RaceTelemetry
    vehicle: VehicleTelemetry
    inputs: DriverInputs
    motion: MotionTelemetry
    position: PositionTelemetry
    wheels: WheelsTelemetry

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready nested dictionary without losing raw values."""
        # This keeps the strict models easy to send through the API.
        return asdict(self)
