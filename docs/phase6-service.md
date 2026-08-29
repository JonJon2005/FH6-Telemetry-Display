# Phase 6: live telemetry service

Phase 6 turns the validated decoder into a continuously running, Windows-safe service. UDP ingestion, binary parsing, in-memory state, HTTP APIs, WebSocket delivery, and debug presentation are separate modules.

## Runtime flow

```text
FH6 UDP :20440
      │
      ▼
TelemetryUDPProtocol ──► TelemetryState ──► validated latest state
                                                │
                              20 Hz publisher ──┤
                                                ▼
                                  LatestValueBroadcaster
                                                │
                              /ws/telemetry ◄───┴──► dashboard clients

Diagnostic API and /ws/debug read the same state lazily; they do not sit in
the UDP receive path.
```

The receiver uses `asyncio.create_datagram_endpoint` with IPv4 APIs available on Windows. Its callback performs bounded in-memory work: count the datagram, validate the length, decode it, validate it, and replace the current state. It performs no disk or network waits.

## Module responsibilities

- `app/main.py`: application factory, FastAPI lifespan, static page, and Uvicorn entry point.
- `app/config.py`: validated environment configuration.
- `app/telemetry/receiver.py`: minimal asyncio UDP protocol adapter.
- `app/telemetry/service.py`: start/stop lifecycle and fixed-rate publisher task.
- `app/telemetry/parser.py`: byte-only decoder with no socket or web dependencies.
- `app/telemetry/state.py`: bounded counters plus latest raw and normalized state.
- `app/telemetry/broadcast.py`: multiple-client latest-value fan-out.
- `app/web/api.py`: HTTP health, realtime snapshot, and debug snapshot routes.
- `app/web/websocket.py`: production and diagnostic WebSocket routes.

Session persistence deliberately remains outside this phase. Phase 9 will attach recording after the validated state boundary without putting SQLite work inside the UDP callback. LAN address discovery and advertised endpoints are implemented in Phase 7.

## Public interfaces

### `GET /health`

Reports service/UDP status, the actual UDP bind, WebSocket client counts, configured broadcast rate, number of broadcasts, and dropped stale client updates. If UDP binding fails, HTTP remains available and reports `degraded` so `/debug` can explain the problem.

### `GET /api/telemetry`

Returns the latest compact production contract once. It contains:

- `schema: "fh6-telemetry-state"`
- `schema_version: 1`
- monotonically increasing valid-packet `sequence`
- connection state and bounded counters
- the latest normalized telemetry model

It excludes raw hex, parser internals, and the 89-field diagnostic table.

### `WS /ws/telemetry`

Publishes the same normalized contract at `FH6_TELEMETRY_PUBLISH_HZ`, defaulting to 20 Hz. The UDP receiver can continue near 60 Hz while browsers redraw less often.

Every client has a one-item queue. When a client cannot keep up, its stale queued frame is replaced by the newest frame. Telemetry ingestion and other clients never wait for it. A send timeout cleans up a stuck connection, and the combined production/debug client count is limited.

### Debug interfaces

`GET /api/debug` and `WS /ws/debug` preserve Phase 5 diagnostics. The debug WebSocket defaults to 10 Hz. `/debug` remains the visible diagnostic page.

## Configuration

| Environment variable | Default | Constraint |
|---|---:|---|
| `FH6_UDP_HOST` | `0.0.0.0` | IPv4 bind address |
| `FH6_UDP_PORT` | `20440` | `0`–`65535` |
| `FH6_HTTP_HOST` | `0.0.0.0` | HTTP bind address |
| `FH6_HTTP_PORT` | `50415` | `0`–`65535` |
| `FH6_TELEMETRY_TIMEOUT` | `2.0` | positive seconds |
| `FH6_TELEMETRY_PUBLISH_HZ` | `20` | `1`–`120` Hz |
| `FH6_DEBUG_PUSH_HZ` | `10` | positive Hz |
| `FH6_WEBSOCKET_SEND_TIMEOUT` | `2.0` | positive seconds |
| `FH6_MAX_WEBSOCKET_CLIENTS` | `32` | positive integer |
| `FH6_LAN_IP` | automatically detected | optional advertised IPv4 override |

Example PowerShell override:

```powershell
$env:FH6_TELEMETRY_PUBLISH_HZ = "30"
$env:FH6_MAX_WEBSOCKET_CLIENTS = "16"
python -m app.main
```

## Failure behavior

- Unexpected packet sizes are counted and retained for raw diagnostics, never parsed.
- A malformed or non-finite value cannot produce invalid JSON.
- A bad packet following a good packet cannot corrupt the last valid decoded field table.
- Several failed sanity checks mark the layout suspicious without crashing the service.
- UDP bind failure leaves HTTP running in degraded mode.
- Slow WebSocket clients lose stale display frames rather than growing memory.
- Startup and shutdown own and close both the UDP transport and publisher task.

All counters and retained state are bounded except lifetime integer counters, whose storage size is constant. No telemetry samples accumulate in memory.

## Verification

The Phase 6 suite contains 56 tests covering parsing, validation, capture/replay, configuration, UDP lifecycle, actual loopback datagrams, API contracts, diagnostic and production WebSockets, two concurrent clients, client limits, slow-client replacement, strict JSON, and UDP bind failure.

The real-capture integration replay received and decoded all 410 packets at 2× speed. The valid sequence reached 410, production publication ran at 20 Hz, the latest packet passed every sanity check, and the debug state exposed all 89 fields.
