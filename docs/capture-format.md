# FH6 raw capture format

Format name: `fh6cap-jsonl`  
Current version: `1`  
Typical extension: `.fh6cap`  
Encoding: UTF-8, newline-delimited JSON (JSONL)

## Purpose

An FH6 capture preserves each received UDP payload byte-for-byte while retaining enough receive metadata to reproduce its timing later. It is a diagnostic and replay format, not a decoded telemetry schema. Unknown and unexpected packet lengths are valid captures.

JSONL was selected because it is streamable, append-friendly, recoverable up to the last complete line after interruption, and understandable without a proprietary reader. Base64 adds storage overhead but preserves arbitrary binary payloads exactly.

## Record ordering

The first line must be exactly one header record. Every later nonblank line must be a packet record. File order is packet receive order and is authoritative for replay ordering.

### Header record

```json
{"type":"header","format":"fh6cap-jsonl","version":1,"created_at":"2026-08-29T21:25:46.795Z","bind_host":"0.0.0.0","bind_port":20440}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | string | Must be `header`. |
| `format` | string | Must be `fh6cap-jsonl`. |
| `version` | integer | Schema version, currently `1`. |
| `created_at` | string | UTC ISO-8601 capture creation time. |
| `bind_host` | string | Address on which the probe listened. |
| `bind_port` | integer | UDP port on which the probe listened, 0–65535. |

### Packet record

```json
{"type":"packet","received_at":"2026-08-29T21:25:46.806Z","received_unix_ns":1788038746806823000,"source_ip":"192.168.1.142","source_port":5200,"length":324,"payload_base64":"AQAAAA..."}
```

| Field | Type | Meaning |
|---|---|---|
| `type` | string | Must be `packet`. |
| `received_at` | string | Human-readable UTC ISO-8601 receive time. |
| `received_unix_ns` | integer | Receive time as Unix nanoseconds; authoritative for replay spacing. |
| `source_ip` | string | Original UDP sender IP. |
| `source_port` | integer | Original UDP sender port, 0–65535. |
| `length` | integer | Original payload length, 0–65535. |
| `payload_base64` | string | Complete UDP payload encoded with standard Base64. |

`length` must equal the number of bytes produced by strict Base64 decoding. A mismatch makes the capture invalid rather than silently truncating or padding it.

## Writer behavior

`tools\udp_probe.py`:

- writes the header before receiving packets;
- writes one packet record per datagram;
- uses the receive order from the UDP socket;
- flushes every line immediately;
- records any UDP payload length without interpreting it;
- creates parent directories when needed;
- refuses to overwrite an existing file unless `--overwrite` is explicit.

The capture grows until the probe stops. Long captures should be monitored for disk usage.

## Reader validation

`tools\replay_capture.py` validates the complete file before sending any packet:

- valid UTF-8 and JSON objects;
- supported format and exact schema version;
- required field presence and primitive types;
- port and length bounds;
- strict Base64 encoding;
- declared-versus-decoded length equality;
- at least one packet record.

Unknown record types and future versions fail closed with a filename and line number. This prevents a newer schema from being misinterpreted as version 1.

## Replay timing

Packet zero is sent immediately. Later packet deadlines are calculated from:

```text
replay start + (packet receive time - first receive time) / speed multiplier
```

Deadlines are absolute, so socket and loop overhead do not accumulate as drift. Sleeps are split into chunks no longer than 250 ms to keep Ctrl+C responsive on Windows.

- `--speed 0.5` doubles the recorded duration.
- `--speed 1` preserves recorded spacing.
- `--speed 2` halves the recorded duration.
- `--speed max` performs no timing sleeps.

If a capture timestamp moves backwards, file order is retained and that packet is clamped to the previous replay offset. The final output reports how many timestamp corrections occurred.

UDP is intentionally preserved as UDP. Delivery, ordering across the network, and receiver capacity are not guaranteed by the transport. Maximum-speed replay is useful for parser/load work, while 1× should be preferred for faithful behavioral testing.

## Integrity reporting

The replay tool prints a SHA-256 digest calculated over the concatenation of decoded payloads in file order. It scans again while sending and requires the packet count, payload-byte count, and payload digest to remain identical. This detects a capture modified between preflight validation and replay.

The digest is a payload-stream integrity aid, not a signature or authentication mechanism. It excludes JSON formatting and metadata.

## Privacy and security

Captures may contain world positions, car identifiers, timing, and driving inputs. Store or share them accordingly. A capture never contains executable instructions, and replay only Base64-decodes validated payloads and sends them as UDP datagrams. Do not expose the replay target or listener through router port forwarding.

## Compatibility policy

Readers accept only explicitly supported versions. A future schema change must increment `version`, document migration behavior, and add compatibility tests. Version 1 fields must not be silently redefined.
