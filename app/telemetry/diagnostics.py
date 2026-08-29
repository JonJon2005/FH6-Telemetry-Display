"""Wire-level field rows for the Phase 5 diagnostic table."""

from __future__ import annotations

import math

from .models import TelemetryPacket
from .parser import FIELD_DEFINITIONS, decode_fields


def diagnostic_rows(data: bytes, packet: TelemetryPacket) -> list[dict[str, object]]:
    # Match each decoded value to its exact place in the raw packet.
    raw = decode_fields(data)
    normalized = _normalized_values(packet)
    rows: list[dict[str, object]] = []
    for definition in FIELD_DEFINITIONS:
        value = raw[definition.name]
        rows.append({
            "name": definition.name,
            "offset": definition.offset,
            "size": definition.size,
            "binary_type": definition.binary_type,
            "source_unit": definition.source_unit,
            "normalized_unit": definition.normalized_unit,
            "confidence": definition.confidence,
            "notes": definition.notes,
            "raw_value": value.hex(" ") if isinstance(value, bytes) else _json_number(value),
            "decoded_value": normalized.get(definition.name, _display(value)),
        })
    return rows


def _json_number(value: int | float) -> int | float | str:
    # Browsers cannot safely parse infinity or NaN as JSON numbers.
    return value if isinstance(value, int) or math.isfinite(value) else str(value)


def _display(value: object) -> str:
    if isinstance(value, bytes):
        return value.hex(" ")
    if isinstance(value, float):
        return f"{value:.6g}" if math.isfinite(value) else str(value)
    return str(value)


def _normalized_values(p: TelemetryPacket) -> dict[str, str]:
    v, r, i, m, w = p.vehicle, p.race, p.inputs, p.motion, p.wheels
    values: dict[str, str] = {
        "IsRaceOn": f"{r.is_race_on}",
        "TimestampMS": f"{r.timestamp_seconds:.3f} s",
        "EngineMaxRpm": f"{v.engine_max_rpm:.1f} rpm",
        "EngineIdleRpm": f"{v.engine_idle_rpm:.1f} rpm",
        "CurrentEngineRpm": f"{v.current_engine_rpm:.1f} rpm ({v.engine_rpm_percent:.1f}%)",
        "Yaw": f"{m.orientation_degrees.x:.2f}°",
        "Pitch": f"{m.orientation_degrees.y:.2f}°",
        "Roll": f"{m.orientation_degrees.z:.2f}°",
        "Speed": f"{v.speed.meters_per_second:.3f} m/s · {v.speed.kilometers_per_hour:.2f} km/h · {v.speed.miles_per_hour:.2f} mph",
        "Power": f"{v.power.kilowatts:.2f} kW · {v.power.mechanical_horsepower:.2f} hp",
        "Torque": f"{v.torque.source_newton_meters:.2f} N·m · {v.torque.pound_feet:.2f} lb-ft",
        "Boost": f"{v.boost.source_psi:.2f} psi · {v.boost.kilopascals:.2f} kPa",
        "Fuel": f"{v.fuel_percent:.1f}%",
        "DistanceTraveled": f"{v.distance_traveled.kilometers:.3f} km · {v.distance_traveled.miles:.3f} mi",
        "DrivetrainType": v.drivetrain.label,
        "Gear": i.gear.label,
        "Accel": f"{i.throttle.percent:.1f}%",
        "Brake": f"{i.brake.percent:.1f}%",
        "Clutch": f"{i.clutch.percent:.1f}%",
        "HandBrake": f"{i.handbrake.percent:.1f}%",
        "Steer": f"{i.steering.percent:+.1f}%",
        "NormalizedDrivingLine": f"{i.normalized_driving_line:+.3f}",
        "NormalizedAIBrakeDifference": f"{i.normalized_ai_brake_difference:+.3f}",
    }
    for axis, value in zip("XYZ", (m.angular_velocity_degrees_per_second.x, m.angular_velocity_degrees_per_second.y, m.angular_velocity_degrees_per_second.z)):
        values[f"AngularVelocity{axis}"] = f"{value:.2f} deg/s"
    for suffix, wheel in (("FrontLeft", w.front_left), ("FrontRight", w.front_right), ("RearLeft", w.rear_left), ("RearRight", w.rear_right)):
        values[f"WheelRotationSpeed{suffix}"] = f"{wheel.rotation_speed_rpm:.1f} rpm"
        values[f"WheelOnRumbleStrip{suffix}"] = str(wheel.on_rumble_strip)
        values[f"WheelInPuddle{suffix}"] = f"S32 {wheel.puddle.as_signed_int32} · F32 {wheel.puddle.as_float32_depth:.6g}"
        values[f"TireTemp{suffix}"] = f"{wheel.tire_temperature.celsius:.1f} °C · {wheel.tire_temperature.source_fahrenheit:.1f} °F"
    return values
