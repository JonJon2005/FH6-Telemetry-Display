# Forza Horizon 6 Data Out protocol research

Research date/access date: **2026-08-29**  
Target game: **Forza Horizon 6**  
Status: research and first local packet verification complete

## Executive conclusion

**CONFIRMED:** FH6 has an official, FH6-specific Data Out document. It specifies a single fixed **324-byte** UDP packet. FH6 does not expose the Motorsport Sled/Dash selector. Fields are tightly packed in the listed order; the shared Sled section occupies offsets 0–231, the Horizon block occupies 232–243, and the dashboard tail begins at 244. The official list accounts for 323 bytes, so byte 323 is a trailing reserved/padding byte.

**CONFIRMED FOR THE TESTED BUILD:** The user's Xbox capture uses little-endian values. Decoded speed agrees with the magnitude of the three velocity components to within 0.0000035 m/s across moving frames. Tire values decode to a physically plausible 124–213 °F (51–101 °C), strongly confirming Fahrenheit for this capture.

**STILL UNVERIFIED:** The first capture did not include a puddle, pause/menu interval, clutch input, or an active lap. Those behaviors and the documented puddle-type conflict still need targeted evidence.

## Local capture evidence

Capture: `captures\first-drive.fh6cap`  
Capture SHA-256: `A040829C21809AD38A4C841FC7B6A2CB91F563A84C0E76A95BDEF35382EDC773`

- 410 of 410 payloads were exactly 324 bytes; no declared/actual length mismatch.
- Xbox sender was `192.168.1.142:5200`; the probe listened on UDP 20440.
- Recorded duration was 6.825 seconds at 59.93 packets/s average.
- Inter-arrival median was 16.678 ms; maximum was 21.115 ms.
- Every `IsRaceOn` value was 1; lap number and race position remained 0, which supports interpreting the field as active driving rather than strictly being in a race.
- Byte 323 was zero in all 410 packets.
- RPM, inputs, suspension, slip, position, power, torque, and temperatures were finite and physically plausible under the proposed layout.
- Raw gear values were 0, 1, 2, and a brief 11 during shifts. The capture supports 0=reverse and 1/2=first/second, while value 11 remains unverified (likely a neutral/shift state).
- Puddle bytes 132–147 were zero throughout, so they cannot resolve S32 boolean versus F32 depth.

## Sources consulted

All sources were accessed 2026-08-29.

1. [Official Forza Horizon 6 Data Out documentation](https://support.forza.net/hc/en-us/articles/51744149102611-Forza-Horizon-6-Data-Out-Documentation) — primary source. It specifies 324 bytes, fields and primitive types, the Horizon-only fields, game-frame-rate transmission, localhost support, and when traffic stops.
2. [Official Forza Motorsport Data Out documentation](https://support.forzamotorsport.net/hc/en-us/articles/21742934024211-Forza-Motorsport-Data-Out-Documentation) — historical/reference primary source. The original support URL currently redirects, so its preserved content was cross-checked through the next source.
3. [Preserved Forza Motorsport documentation in streamdeck-forza-telemetry](https://github.com/shiguruikai/streamdeck-forza-telemetry/blob/main/docs/forza-telemetry/fm8.md) — records the official Motorsport Sled/Dash distinction, 60 packets/s, and Motorsport localhost support.
4. [Forza Motorsport 7 Data Out announcement](https://forums.forza.net/t/forza-motorsport-7-data-out-feature-details/74013) — historical official forum material describing the 232-byte Sled base and the later Dash extension. The old forum now redirects, but indexed content remains available.
5. [ClickClickMedia/Forza-6-telemetry parser](https://github.com/ClickClickMedia/Forza-6-telemetry/blob/main/app/packet.py) — independent Python implementation. It requires 324 bytes, constructs an explicit little-endian struct, includes the 12-byte Horizon block, and reports live FH6 physics cross-checks.
6. [viunow/fh6-telemetry parser](https://github.com/viunow/fh6-telemetry/blob/main/src/parser.js) — independent JavaScript implementation. It uses explicit little-endian Buffer reads, the same offsets, and Fahrenheit-to-Celsius conversion. It accepts packets of 323 bytes or longer rather than requiring exactly 324.
7. [ForzaTuningAdvisor FH6 format notes](https://github.com/Tautellini/ForzaTuningAdvisor/blob/main/Docs/forza-data-format.md) — reports a live 324-byte capture, little-endian decoding, inputs, tire temperature behavior, and speed/velocity validation. Some historical comparisons conflict with older Horizon evidence; see below.
8. [acaranta/fh6-telemetry-dashboard offset table](https://github.com/acaranta/fh6-telemetry-dashboard/blob/master/src/server/telemetry/offsets.ts) — an explicitly **unverified** FH6 implementation. Useful as evidence of uncertainty, not authority.
9. [richstokes/Forza-data-tools FH4 layout](https://github.com/richstokes/Forza-data-tools/blob/master/FH4_packetformat.dat) — older Horizon reference showing that the 12-byte block and 324-byte layout predate FH6.
10. [geeooff/forza-data-web](https://github.com/geeooff/forza-data-web) — cross-game implementation distinguishing forced Horizon Dash from Motorsport Sled/Dash and documenting the formerly unknown Horizon extras.

Searches also located projects named `fh6-tel`, `fh6-web`/FH6 Oversight Dashboard, `fh6-telemetry-dashboard`, and several new telemetry utilities. They broadly agree on UDP and a 324-byte Horizon packet, but only source code that could be inspected was used for the detailed cross-check.

## Confidence key

- **CONFIRMED** — stated by the official FH6 documentation, or mathematically forced by that layout.
- **LIKELY** — supported by two or more independent implementations and/or reported live-capture tests, but omitted or contradicted by the official page.
- **UNVERIFIED** — insufficient evidence or behavior that needs a controlled local capture.

## Wire-level findings

| Property | Status | Finding |
|---|---|---|
| Transport | CONFIRMED | One-way UDP to the configured destination IP and port. |
| Packet length | CONFIRMED | Fixed 324 bytes. Unexpected lengths should still be captured diagnostically, never crash the probe. |
| Byte order | LIKELY | Little-endian for all multi-byte scalars. Both inspected parsers use LE; reported live physics checks validate it. |
| Packing | CONFIRMED | Packed field order, no alignment gaps inside the listed fields. One final byte remains after the 323 listed bytes. |
| Frequency | CONFIRMED | Equal to the game's frame rate, not a guaranteed fixed 60 Hz. Around 60 packets/s is common at 60 FPS. |
| FH6 format choices | CONFIRMED | One fixed Horizon packet; no Sled/Dash selector. |
| Sled-compatible prefix | CONFIRMED | Bytes 0–231 match the traditional Sled field sequence. |
| Horizon block | CONFIRMED | `CarGroup`, `SmashableVelDiff`, `SmashableMass` at 232–243. |
| Dash tail | CONFIRMED | Starts with `PositionX` at byte 244. |
| Trailing byte | LIKELY | Byte 323 is padding/reserved, commonly observed as zero; official fields stop at 322 while total size is 324. |
| Pauses/menus | CONFIRMED | Officially, no packets are sent in menus, pauses, replays, rewinds, or after a race finishes. |
| Timestamp | CONFIRMED/PARTIAL | Unsigned milliseconds and can wrap to zero. Epoch/origin and pause/reset behavior are not documented. |
| Localhost | CONFIRMED | FH6 supports `127.0.0.1` when game and receiver run on the same PC. |
| Source port | UNVERIFIED | Not fixed by the protocol. FH6 docs warn against destination ports 5200–5300 because the game binds its outgoing socket in that range. |

## Proposed packet layout (not yet implemented as a production parser)

All offsets are zero-based. `S32`/`U32` are signed/unsigned 32-bit integers; `F32` is IEEE-754 single precision; `U16`, `U8`, and `S8` have their usual widths. `FL/FR/RL/RR` means front-left/front-right/rear-left/rear-right.

| Offset(s) | Type | Field(s) | Source unit/meaning | Confidence |
|---:|---|---|---|---|
| 0 | S32 | IsRaceOn | 1 driving/race active, 0 stopped | CONFIRMED |
| 4 | U32 | TimestampMS | milliseconds; wraps | CONFIRMED |
| 8, 12, 16 | F32 ×3 | EngineMaxRpm, EngineIdleRpm, CurrentEngineRpm | rpm | CONFIRMED name/type; unit implicit |
| 20, 24, 28 | F32 ×3 | Acceleration X/Y/Z | local axes: right/up/forward; likely m/s² | CONFIRMED axes, LIKELY unit |
| 32, 36, 40 | F32 ×3 | Velocity X/Y/Z | local axes: right/up/forward; likely m/s | CONFIRMED axes, LIKELY unit |
| 44, 48, 52 | F32 ×3 | AngularVelocity X/Y/Z | local pitch/yaw/roll, rad/s | CONFIRMED |
| 56, 60, 64 | F32 ×3 | Yaw, Pitch, Roll | radians | CONFIRMED |
| 68, 72, 76, 80 | F32 ×4 | NormalizedSuspensionTravel FL/FR/RL/RR | 0 max stretch, 1 max compression | CONFIRMED |
| 84, 88, 92, 96 | F32 ×4 | TireSlipRatio FL/FR/RL/RR | normalized; 0 grip, magnitude >1 loss | CONFIRMED |
| 100, 104, 108, 112 | F32 ×4 | WheelRotationSpeed FL/FR/RL/RR | rad/s | CONFIRMED |
| 116, 120, 124, 128 | S32 ×4 | WheelOnRumbleStrip FL/FR/RL/RR | 0/1 | CONFIRMED |
| 132, 136, 140, 144 | 4 bytes ×4 | WheelInPuddle… | **conflict:** FH6 page says S32 boolean; historical format and both parsers use F32 depth 0–1 | UNVERIFIED |
| 148, 152, 156, 160 | F32 ×4 | SurfaceRumble FL/FR/RL/RR | non-dimensional force-feedback value | CONFIRMED |
| 164, 168, 172, 176 | F32 ×4 | TireSlipAngle FL/FR/RL/RR | normalized; magnitude >1 loss of grip | CONFIRMED |
| 180, 184, 188, 192 | F32 ×4 | TireCombinedSlip FL/FR/RL/RR | normalized; magnitude >1 loss of grip | CONFIRMED |
| 196, 200, 204, 208 | F32 ×4 | SuspensionTravelMeters FL/FR/RL/RR | meters | CONFIRMED |
| 212 | S32 | CarOrdinal | model identifier | CONFIRMED |
| 216 | S32 | CarClass | 0=D through 7=X | CONFIRMED |
| 220 | S32 | CarPerformanceIndex | documented 100–999 | CONFIRMED |
| 224 | S32 | DrivetrainType | 0 FWD, 1 RWD, 2 AWD | CONFIRMED |
| 228 | S32 | NumCylinders | count | CONFIRMED |
| 232 | U32 | CarGroup | car-group identifier | CONFIRMED (some parsers use S32) |
| 236 | F32 | SmashableVelDiff | velocity loss, m/s | CONFIRMED |
| 240 | F32 | SmashableMass | kg | CONFIRMED |
| 244, 248, 252 | F32 ×3 | Position X/Y/Z | world coordinates, meters | CONFIRMED |
| 256 | F32 | Speed | m/s | CONFIRMED |
| 260 | F32 | Power | watts | CONFIRMED |
| 264 | F32 | Torque | N·m | CONFIRMED |
| 268, 272, 276, 280 | F32 ×4 | TireTemp FL/FR/RL/RR | likely °F on wire | LIKELY |
| 284 | F32 | Boost | PSI above atmosphere | CONFIRMED |
| 288 | F32 | Fuel | 0 empty–1 full | CONFIRMED |
| 292 | F32 | DistanceTraveled | meters | CONFIRMED |
| 296, 300, 304 | F32 ×3 | BestLap, LastLap, CurrentLap | seconds; 0 if not applicable | CONFIRMED |
| 308 | F32 | CurrentRaceTime | seconds since driving began | CONFIRMED |
| 312 | U16 | LapNumber | completed-lap count | CONFIRMED |
| 314 | U8 | RacePosition | position | CONFIRMED |
| 315, 316, 317, 318 | U8 ×4 | Accel, Brake, Clutch, HandBrake | 0–255 | CONFIRMED |
| 319 | U8 | Gear | current gear; numeric-to-label mapping undocumented | CONFIRMED type, UNVERIFIED mapping |
| 320 | S8 | Steer | −127 full left, 0 center, 127 full right | CONFIRMED |
| 321 | S8 | NormalizedDrivingLine | −127–127 | CONFIRMED |
| 322 | S8 | NormalizedAIBrakeDifference | −127–127 | CONFIRMED |
| 323 | U8/reserved | trailing byte | usually reported as zero | LIKELY |

### Offset arithmetic

The official sequence gives `232-byte Sled prefix + 12-byte Horizon block + 79-byte Dash tail = 323 bytes`. The official total is 324 bytes, leaving byte 323. Community implementations either treat it as padding/unknown or accept a 323-byte truncated packet. The production receiver should require the official 324 bytes for decoding but retain all other sizes as unknown diagnostics.

## Important discrepancies

### FH6 versus FH5

ForzaTuningAdvisor says the FH6 dash tail is shifted +12 bytes “vs FH5.” That wording conflicts with older FH4/FH5 sources: `FH4_packetformat.dat` and cross-game parsers already describe a 324-byte Horizon layout with a 12-byte block after `NumCylinders`, placing `PositionX` at 244. Newer live-tested FH6 parsers also say FH4/FH5/FH6 are wire-compatible.

Our conclusion is **LIKELY** that FH6 did not newly insert those 12 bytes versus FH5; rather, FH6's official documentation finally assigns names/types to bytes older Horizon parsers often called unknown. A real FH5-versus-FH6 capture comparison would be needed to elevate that conclusion.

### FH6 versus Forza Motorsport

- FH6 has one forced 324-byte Horizon format; Motorsport offers Sled and Dash choices.
- FM7 Sled is 232 bytes and FM7 Dash is 311 bytes.
- Motorsport (2023) Dash is reported as 331 bytes because it includes four `TireWear` floats and `TrackOrdinal`.
- FH6 instead places the 12-byte Horizon block at 232–243 and has neither `TireWear` nor `TrackOrdinal`.
- Current Motorsport documentation says 60 packets/s; current FH6 documentation says game-frame-rate packets.

### Puddle fields

The FH6 page labels four fields `S32 WheelInPuddle…` with boolean semantics. The historical official structure and both inspected FH6 parser sources decode the same bytes as `F32 WheelInPuddleDepth…` in a 0–1 range. Size and downstream offsets are unaffected, but values/meaning are not. Capture a controlled dry-road/puddle sequence and inspect bytes 132–147 both ways before choosing.

### Tire-temperature unit

The official FH6 page omits a unit. Multiple independent projects decode plausible values as Fahrenheit and convert to Celsius. This remains **LIKELY**, not officially confirmed. A capture after cold start and a warmed run should make the unit obvious.

### Paused/menu behavior

The official FH6 page says transmission stops in menus and pauses. One community note says zero-filled frames arrive when `IsRaceOn == 0`. These behaviors conflict. The probe's stop warning and byte-exact capture are intentionally able to distinguish silence from zero packets on the user's build.

### Length acceptance

Official length is exactly 324. The viunow parser accepts 323 bytes or more, and acaranta sets a 323-byte minimum with 324 expected. That leniency is useful for recovery but should not define the production wire contract. The diagnostic probe accepts every UDP length; the eventual parser should only decode explicitly recognized layouts.

## Facts that remain unverified

- Whether every platform/store build sends identical bytes and rates.
- Whether any future game update introduces a second packet length.
- Exact timestamp origin and whether it resets across cars/sessions; only millisecond width and wrap are documented.
- Gear byte labels, especially reverse and neutral.
- Temperature unit, despite strong Fahrenheit evidence.
- World-coordinate origin, handedness, map bounds, and whether axes ever reset.
- Exact units for linear acceleration and velocity (their axes are documented).
- Whether `IsRaceOn` should be interpreted as “actively driving” in free roam or strictly “in a race.”
- Whether pause/menu behavior is total silence on all builds or sometimes zero-filled frames.
- Whether the trailing byte can ever be nonzero.

## Empirical verification plan

Capture at least 60 seconds while performing these actions in order, speaking or noting approximate times:

1. Remain stationary for 5 seconds.
2. Rev while stationary.
3. Accelerate and hold a known approximate speed.
4. Brake to a stop.
5. Steer fully left, center, fully right.
6. Select reverse and each available forward gear.
7. Drive through a puddle and over a rumble strip if practical.
8. Pause for 5 seconds, resume, enter/leave a race.

Then verify:

- size frequency is dominated by exactly 324;
- rate follows frame rate;
- timestamp changes in milliseconds and its pause behavior is observed;
- speed at offset 256 approximately equals `sqrt(VelocityX² + VelocityY² + VelocityZ²)`;
- input bytes at 315–318 track controlled inputs;
- steering byte at 320 reaches the documented signs/range;
- bytes 132–147 distinguish the puddle type conflict;
- temperature magnitude distinguishes °F from °C;
- traffic silence versus zero packets during pause/menu is recorded;
- gear byte mapping is derived from controlled shifts.

Real captured packets win over every source above. Any correction should update this document and receive an offset regression test before a production parser is added.
