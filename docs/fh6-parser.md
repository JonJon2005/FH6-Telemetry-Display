# FH6 production packet parser

Parser version: `fh6-324-v1`  
Module: `app\telemetry\parser.py`  
Model module: `app\telemetry\models.py`  
Accepted wire size: exactly 324 bytes

## Scope

This parser is a pure binary transformation:

```text
bytes (exactly 324)
    → little-endian raw field values
    → immutable nested TelemetryPacket
```

It performs no socket I/O, global-state updates, recording, or WebSocket work. Keeping the wire decoder separate makes it usable by the future live receiver, capture replay, regression tests, and debug tooling without duplicating offsets.

## Basic API

```python
from app.telemetry.parser import PacketLengthError, parse_packet

try:
    telemetry = parse_packet(payload)
except PacketLengthError as error:
    print(error)
else:
    print(telemetry.vehicle.speed.miles_per_hour)
    print(telemetry.inputs.throttle.percent)
    print(telemetry.wheels.front_left.tire_temperature.celsius)
```

`parse_packet` rejects every length other than 324. It does not guess between FH6, FM7, FH5, or Motorsport formats. Unknown datagrams remain the responsibility of the diagnostic/receiver layer.

For raw field inspection:

```python
from app.telemetry.parser import FIELD_DEFINITIONS, decode_fields

raw = decode_fields(payload)
for definition in FIELD_DEFINITIONS:
    print(
        definition.name,
        definition.offset,
        definition.binary_type,
        definition.source_unit,
        raw[definition.name],
    )
```

## Model structure

`TelemetryPacket` is composed of frozen, slotted dataclasses:

```text
TelemetryPacket
├── metadata       format, parser version, packet size, reserved byte
├── race           active-driving flag, timestamp, laps, race time/position
├── vehicle        identity, RPM, drivetrain, speed, power, torque, boost, fuel
├── inputs         pedals, handbrake, steering, gear, driving-line fields
├── motion         acceleration, velocity, angular velocity, orientation
├── position       world-space coordinates
└── wheels
    ├── front_left
    ├── front_right
    ├── rear_left
    └── rear_right
```

`TelemetryPacket.to_dict()` returns a nested dictionary ready for later JSON serialization. The dataclasses are immutable so browser/state consumers cannot accidentally mutate a decoded packet shared with another component.

## Raw and normalized values

Wire values remain available alongside conversions:

| Source value | Exposed values |
|---|---|
| Speed in m/s | m/s, km/h, mph |
| Tire temperature in °F | source °F, °C |
| Power in watts | watts, kW, mechanical horsepower |
| Torque in N·m | N·m, lb-ft |
| Boost in psi | psi, kPa |
| Distance in meters | meters, km, miles |
| Fuel fraction | fraction, percent |
| Pedal/handbrake U8 | raw 0–255, normalized 0–1, percent |
| Steering S8 | raw −127–127, normalized −1–1, signed percent |
| RPM | raw RPM, current/max fraction and percent |
| Angles in radians | radians and degrees |
| Angular velocity in rad/s | rad/s and deg/s |
| Wheel rotation in rad/s | rad/s and RPM |
| Timestamp in milliseconds | milliseconds and seconds |

Conversions are not clamped except where a signed control is mapped to its documented normalized range. Preserving an out-of-range source value is important for the sanity-check phase.

## Auditable field metadata

`FIELD_DEFINITIONS` is the parser's ordered wire contract. Every entry records:

- official field name;
- zero-based byte offset;
- primitive type and size;
- source unit;
- normalized unit(s);
- confidence and conflict notes where applicable.

An import-time assertion requires the 89 entries to be unique, contiguous, and cover exactly 324 bytes. Tests separately pin important anchor offsets. The complete human-readable layout and source rationale remain in [the protocol research](fh6-protocol-research.md).

## Explicit uncertainty policy

### Puddle fields

Official FH6 documentation describes bytes 132–147 as four S32 flags. Historical documentation and independent parsers describe four F32 depths. The first local capture contained only zero bytes there, which cannot distinguish the encodings.

Each wheel therefore exposes a `PuddleReading` containing:

- exact four bytes as hexadecimal;
- little-endian signed-int interpretation;
- little-endian float interpretation;
- an explicit unresolved label.

No interpretation is selected until a controlled puddle capture provides evidence.

### Gear

The official document supplies a U8 but no value mapping. The first local capture confirms raw 0 while reverse was selected and raw 1/2 while driving in first/second. Raw 11 appeared transiently around shifts. The model labels 0 as `R`, 1–10 as forward gear numbers, and every other value as unknown. Raw 11 additionally carries an `is_unverified_shift_state` marker but is not labeled neutral.

### Acceleration

The local axes are official, but the FH6 page omits a unit. The model preserves the three source floats and labels their unit `unverified; likely meters per second squared`. It does not derive G-force yet.

## First-capture validation

All 410 packets from `captures\first-drive.fh6cap` decode successfully. Across moving frames, parsed `Speed` differs from the magnitude of parsed `VelocityX/Y/Z` by less than 0.00001 m/s. The real-capture test runs automatically when that user-owned capture is present and skips cleanly when it is absent.

Phase 5 will add behavioral sanity results, detailed raw/decoded diagnostics, and controlled-capture regression fixtures. Those policies deliberately do not live inside this Phase 4 wire transformation.
