# Phase 5: live parser validation and diagnostic UI

Phase 5 adds a small local web service around the Phase 4 decoder. It listens for FH6 UDP telemetry on port `20440` and publishes a live diagnostic page on TCP port `50415`.

## Start it

From PowerShell in the project folder:

```powershell
pip install -r requirements.txt
python -m app.main
```

Open <http://localhost:50415/debug>. Leave that terminal open while testing. Stop the service with `Ctrl+C`.

On Xbox, keep the FH6 Data Out destination set to the Windows PC's LAN IPv4 address and UDP port `20440`. Do not put `50415` in FH6; that is only the browser port.

The old UDP probe and this service cannot both listen on UDP `20440`. Close the probe before starting the UI.

## Test without FH6

With the service running, replay the first capture from a second PowerShell window:

```powershell
python tools\replay_capture.py captures\first-drive.fh6cap --speed 1
```

The status should change to **Telemetry live**, the rate should settle near 60 packets/second, and the gauges and field table should update. After the replay stops, the page intentionally changes to a stopped/waiting state after two seconds while retaining the last decoded values.

## What the page proves

- **UDP status** confirms whether the receiver successfully owns the configured port.
- **Traffic active** means some UDP bytes are arriving; **Telemetry live** requires a recently decoded 324-byte FH6 packet.
- Connection details show sender IP/port, packet rate, total packets, last packet time, and every observed packet size.
- Live cards show speed, gear, RPM, pedals, handbrake, steering, tire temperatures, power, torque, boost, fuel, motion, and race state.
- Parser health runs conservative range and cross-field checks. Three or more important failures mark the selected layout as probably incorrect.
- The field inspector exposes every field's raw value, decoded value, byte offset/range, binary type, source unit, and confidence.
- The raw panel retains the latest datagram as a complete hex and ASCII dump.

Warnings do not discard a packet. Raw gear code `11`, for example, remains an informational unverified shift state. The puddle fields expose both signed-integer and float interpretations because that protocol detail remains unresolved.

## Configuration

Environment variables can change the defaults for one PowerShell session:

```powershell
$env:FH6_UDP_HOST = "0.0.0.0"
$env:FH6_UDP_PORT = "20440"
$env:FH6_HTTP_HOST = "0.0.0.0"
$env:FH6_HTTP_PORT = "50415"
$env:FH6_TELEMETRY_TIMEOUT = "2.0"
$env:FH6_TELEMETRY_PUBLISH_HZ = "20"
$env:FH6_DEBUG_PUSH_HZ = "10"
python -m app.main
```

To test on spare ports, set UDP `20441` and HTTP `18080`, then replay using `--port 20441` and open `http://localhost:18080/debug`.

## Troubleshooting

- **UDP error:** another program probably owns the port. Close the probe or other service instance, then restart.
- **Waiting for telemetry:** verify the Xbox destination and actively drive rather than staying in a menu or paused state.
- **Traffic not recognized:** UDP arrives, but its latest size is not the supported 324-byte format. Inspect observed sizes and raw hex.
- **Page opens only on this PC:** TCP `50415` may need a Private-network Windows Firewall rule when viewing from another device.
- **UI reconnecting:** the browser automatically polls the JSON endpoint and retries its WebSocket.

Machine-readable diagnostic endpoints are `/health`, `/api/debug`, and `/ws/debug`. Phase 6 adds the compact production endpoints `/api/telemetry` and `/ws/telemetry`.

## First-capture result

The end-to-end Phase 5 check replayed all 410 recorded packets at 2× speed. The receiver accepted all 410, recognized the latest packet, exposed all 89 fields, and passed all 28 sanity checks. The replay payload SHA-256 remained `68232964744d1c52b3daf3e37e5a424097986e488db9ec0762ccaa9cfac1f939`.
