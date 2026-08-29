"""Conservative sanity checks for decoded FH6 telemetry."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .models import TelemetryPacket


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    severity: str
    field: str
    message: str
    value: object


@dataclass(frozen=True, slots=True)
class ValidationResult:
    layout_likely_valid: bool
    checks_passed: int
    checks_failed: int
    important_failures: int
    issues: tuple[ValidationIssue, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def validate_telemetry(packet: TelemetryPacket) -> ValidationResult:
    # These ranges catch a wrong layout without rejecting normal driving.
    issues: list[ValidationIssue] = []
    passed = 0
    failed = 0
    important = 0

    def check(condition: bool, field: str, message: str, value: object, *, severity: str = "error") -> None:
        # Collect every issue so the debug page can show them together.
        nonlocal passed, failed, important
        if condition:
            passed += 1
            return
        failed += 1
        if severity == "error":
            important += 1
        issues.append(ValidationIssue(severity, field, message, value))

    r = packet.race
    v = packet.vehicle
    i = packet.inputs
    wheels = (
        ("FrontLeft", packet.wheels.front_left),
        ("FrontRight", packet.wheels.front_right),
        ("RearLeft", packet.wheels.rear_left),
        ("RearRight", packet.wheels.rear_right),
    )

    check(r.raw_is_race_on in (0, 1), "IsRaceOn", "expected the active-driving flag to be 0 or 1", r.raw_is_race_on)
    check(math.isfinite(v.engine_max_rpm) and 0 <= v.engine_max_rpm <= 30000, "EngineMaxRpm", "expected 0–30,000 rpm", v.engine_max_rpm)
    check(math.isfinite(v.engine_idle_rpm) and 0 <= v.engine_idle_rpm <= 5000, "EngineIdleRpm", "expected 0–5,000 rpm", v.engine_idle_rpm)
    check(math.isfinite(v.current_engine_rpm) and 0 <= v.current_engine_rpm <= 30000, "CurrentEngineRpm", "expected 0–30,000 rpm", v.current_engine_rpm)
    check(v.engine_max_rpm == 0 or v.engine_idle_rpm <= v.engine_max_rpm, "EngineIdleRpm", "idle RPM should not exceed maximum RPM", v.engine_idle_rpm)
    check(math.isfinite(v.speed.meters_per_second) and 0 <= v.speed.meters_per_second <= 200, "Speed", "expected 0–200 m/s", v.speed.meters_per_second)

    velocity = packet.motion.velocity_meters_per_second.magnitude()
    tolerance = max(0.5, abs(v.speed.meters_per_second) * 0.05)
    check(math.isfinite(velocity) and abs(velocity - v.speed.meters_per_second) <= tolerance, "VelocityX", "velocity magnitude should closely match Speed", velocity)
    check(math.isfinite(v.fuel_fraction) and 0 <= v.fuel_fraction <= 1.05, "Fuel", "expected a 0–1 fuel fraction", v.fuel_fraction)
    check(v.car_class in range(0, 8), "CarClass", "expected class code 0–7", v.car_class)
    check(v.drivetrain.raw in (0, 1, 2), "DrivetrainType", "expected 0 FWD, 1 RWD, or 2 AWD", v.drivetrain.raw)
    check(0 <= v.cylinder_count <= 24, "NumCylinders", "expected 0–24 cylinders", v.cylinder_count)
    check(i.gear.raw <= 11, "Gear", "expected reverse, gears 1–10, or the observed unverified shift state 11", i.gear.raw)

    for name, wheel in wheels:
        check(math.isfinite(wheel.tire_temperature.source_fahrenheit) and -40 <= wheel.tire_temperature.source_fahrenheit <= 500, f"TireTemp{name}", "expected −40–500 °F", wheel.tire_temperature.source_fahrenheit)
        check(math.isfinite(wheel.normalized_suspension_travel) and -0.5 <= wheel.normalized_suspension_travel <= 1.5, f"NormalizedSuspensionTravel{name}", "expected suspension travel near 0–1", wheel.normalized_suspension_travel, severity="warning")
        check(wheel.raw_on_rumble_strip in (0, 1), f"WheelOnRumbleStrip{name}", "expected flag 0 or 1", wheel.raw_on_rumble_strip, severity="warning")

    for name, value in (
        ("BestLap", r.best_lap_seconds),
        ("LastLap", r.last_lap_seconds),
        ("CurrentLap", r.current_lap_seconds),
        ("CurrentRaceTime", r.current_race_time_seconds),
    ):
        check(math.isfinite(value) and value >= 0, name, "expected a finite non-negative time", value)

    if i.gear.is_unverified_shift_state:
        issues.append(ValidationIssue("info", "Gear", "raw gear 11 was observed during shifts but remains unverified", i.gear.raw))
    if packet.metadata.trailing_reserved_byte != 0:
        issues.append(ValidationIssue("warning", "ReservedTrailingByte", "reserved byte was non-zero", packet.metadata.trailing_reserved_byte))

    likely_valid = important < 3
    if not likely_valid:
        issues.insert(0, ValidationIssue("error", "layout", "multiple important checks failed; the selected packet layout is probably incorrect", important))
    return ValidationResult(likely_valid, passed, failed, important, tuple(issues))
