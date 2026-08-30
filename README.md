# FH6 Telemetry Display — live driving dashboard milestone

This is the first testable milestone for a Windows-first, self-hosted Forza Horizon 6 telemetry application. It contains:

- protocol research with source links and confidence levels;
- a UDP probe that accepts any packet length without parsing or crashing;
- a versioned, byte-exact raw capture option;
- a UDP replay tool with original, scaled, or maximum-speed timing;
- a strict 324-byte FH6 decoder with immutable normalized models;
- a live UDP receiver and responsive browser diagnostic page;
- a rate-limited normalized WebSocket service for multiple dashboard clients;
- Windows-safe startup/shutdown, slow-client protection, and degraded health reporting;
- Windows default-route LAN discovery with virtual-adapter filtering and an explicit override;
- exact startup instructions for the Xbox UDP target and LAN browser URL;
- a polished responsive driving dashboard for desktop, mobile, and landscape tablets;
- background SQLite session recording with streamed CSV and JSON exports;
- persistent cross-platform configuration, rotating logs, and single-instance protection;
- parser sanity checks, raw hex inspection, and an 89-field wire table;
- automated unit and loopback integration tests.

The first two desktop-runtime steps are complete: the service now records durable driving sessions and has the configuration, logging, ownership, and graceful-shutdown foundation needed for packaging. Analytics UI and deployment packaging remain later phases.

The Windows tray build is now available as a portable `FH6 Telemetry.exe` with
run-at-sign-in settings, local/LAN quick links, port controls, and background
service status. See [the Windows tray app guide](docs/windows-tray-app.md).

See [the protocol research](docs/fh6-protocol-research.md) for the current 324-byte finding and unresolved protocol conflicts.

The decoder API, model structure, conversion policy, and intentionally unresolved fields are documented in [the parser guide](docs/fh6-parser.md).

The live UI, validation behavior, configuration, and troubleshooting steps are documented in [the Phase 5 guide](docs/phase5-validation.md).

The service architecture, realtime contract, backpressure behavior, and runtime settings are documented in [the Phase 6 guide](docs/phase6-service.md).

Windows LAN discovery, exact device URLs, address overrides, and multi-adapter troubleshooting are documented in [the Phase 7 guide](docs/phase7-lan-access.md).

Dashboard instruments, controls, responsive behavior, and realtime delivery are documented in [the Phase 8 guide](docs/phase8-dashboard.md).

Session boundaries, exports, permanent data locations, log rotation, configuration precedence, and single-instance behavior are documented in [the Phase 9 runtime guide](docs/phase9-runtime-foundation.md).

## Run the live dashboard

```powershell
pip install -r requirements.txt
python -m app.main
```

For the tray experience while developing, install the requirements and run:

```powershell
python -m app.tray
```

Open <http://localhost:50415>. It redirects to the main dashboard. The parser/network engineering view remains at <http://localhost:50415/debug>. FH6 on Xbox should still send to this PC's LAN IPv4 address on UDP port `20440`. Close `udp_probe.py` first because only one process can listen on that port.

To see the UI work from the saved capture without running FH6, keep the service open and run this in a second PowerShell window:

```powershell
python tools\replay_capture.py captures\first-drive.fh6cap --speed 1
```

## Requirements and setup (Windows 10)

Install Python 3.12 or newer. In PowerShell, from the project folder:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest
```

If PowerShell blocks activation, change policy only for the current PowerShell process, then activate:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.venv\Scripts\Activate.ps1
```

This expires when that PowerShell window closes; it does not permanently weaken the machine policy. Command Prompt alternative:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m pytest
```

The probe and replay utilities use only Python's standard library. The live service uses FastAPI and Uvicorn; `pytest` and the HTTP test client support the test suite.

## 1. Find the Windows PC's LAN IPv4 address

In Command Prompt or PowerShell:

```text
ipconfig
```

Find the active **Ethernet** or **Wi-Fi** adapter connected to the same home network as the Xbox/FH6 device. Use its `IPv4 Address`, for example:

```text
IPv4 Address. . . . . . . . . . . : 192.168.1.50
```

PowerShell can also list IPv4 addresses:

```powershell
Get-NetIPAddress -AddressFamily IPv4 | Format-Table InterfaceAlias,IPAddress,AddressState
```

Do not give a different FH6 device `127.0.0.1`, `localhost`, a VPN IP, Hyper-V/WSL/Docker virtual-adapter IP, disconnected-adapter IP, or an Automatic Private `169.254.x.x` address. Use the address on the active physical adapter and default route. `Get-NetRoute -DestinationPrefix '0.0.0.0/0'` can help identify that adapter.

## 2. Start the UDP probe

The UDP telemetry port is **20440**. It is not an HTTP port.

```powershell
python tools\udp_probe.py --port 20440
```

To save a byte-exact capture:

```powershell
python tools\udp_probe.py --port 20440 --capture captures\test.fh6cap
```

The probe will not overwrite an existing capture unless you explicitly add `--overwrite`. It prints the first packet, a roughly once-per-second live sample, source IP/port, packet length, recent packets/sec, timestamp, and a hex preview. Use `--verbose` only if you truly want one console report per packet. After traffic has begun, two seconds of silence produces a warning. Press `Ctrl+C` for a final length/sender summary.

Useful options:

```powershell
python tools\udp_probe.py --help
python tools\udp_probe.py --host 0.0.0.0 --port 20440 --hex-bytes 64 --stop-timeout 3
```

Expected research result is 324-byte packets, but the probe does not assume that and will count/capture any datagram. Do not fake or manually edit the resulting capture.

## 3. Configure FH6 Data Out

In FH6, open **Settings → HUD and Gameplay → Data Out** and set:

```text
Data Out = On
Data Out IP Address = 192.168.1.50    (replace with your PC's LAN IPv4)
Data Out IP Port = 20440
```

Do not enter the HTTP dashboard port `50415` here. UDP `20440` is game telemetry; TCP `50415` serves the browser UI.

If FH6 and the probe run on the **same Windows PC**, use `127.0.0.1`; the official FH6 documentation explicitly confirms localhost support. Use the receiver PC's LAN IPv4 when FH6 is on an Xbox or a different PC. FH6 warns against choosing destination ports 5200–5300 because it uses a source socket in that range; the default 20440 avoids this issue.

Start driving. Official documentation says FH6 only sends while actively driving, not in menus, pauses, replays, rewinds, or after finishing a race.

## 4. Windows Defender Firewall

The first time Python listens, Windows may show a firewall prompt. Allow Python on **Private networks** only. Do not enable Public networks unless you understand and need that exposure.

To review the app permission manually, open **Start → Windows Security → Firewall & network protection → Allow an app through firewall → Change settings**. Find the Python interpreter you are using, enable **Private**, and leave **Public** cleared. If several Python entries exist, PowerShell shows the active interpreter path with:

```powershell
(Get-Command python).Source
```

If Python is not listed, use **Allow another app… → Browse** and select that exact `python.exe`. A port-scoped rule is often clearer for this project and is shown next.

For a narrowly scoped port rule, open PowerShell **as Administrator**, review, then run:

```powershell
New-NetFirewallRule -DisplayName "FH6 Telemetry UDP 20440" -Direction Inbound -Action Allow -Protocol UDP -LocalPort 20440 -Profile Private
```

This allows inbound UDP only on local port 20440 for Private-profile networks. It does not configure the router, port forwarding, or internet access.

Viewing the dashboard from another LAN device may also need TCP 50415:

```powershell
New-NetFirewallRule -DisplayName "FH6 Dashboard TCP 50415" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 50415 -Profile Private
```

That TCP rule is not needed when the browser is on the same PC. Inspect rules:

```powershell
Get-NetFirewallRule -DisplayName "FH6 Telemetry UDP 20440","FH6 Dashboard TCP 50415" | Format-Table DisplayName,Enabled,Profile,Direction,Action
```

Remove them later:

```powershell
Remove-NetFirewallRule -DisplayName "FH6 Telemetry UDP 20440"
Remove-NetFirewallRule -DisplayName "FH6 Dashboard TCP 50415"
```

These commands change Windows Firewall, so they are documented rather than executed automatically.

## 5. Verify packets are arriving

With the probe running, another PowerShell window can confirm the UDP bind and owning process:

```powershell
Get-NetUDPEndpoint -LocalPort 20440 | Format-Table LocalAddress,LocalPort,OwningProcess
```

Command Prompt alternative:

```text
netstat -ano -p udp | findstr :20440
```

You should see `0.0.0.0:20440`, not only `127.0.0.1:20440`, for packets coming from another device.

If the probe reports zero packets:

1. Confirm it is bound to `0.0.0.0:20440`.
2. Confirm FH6 uses the active PC LAN IPv4 and UDP port 20440.
3. Confirm Windows classifies the home connection as Private and the UDP rule is enabled.
4. Disable or route around a VPN temporarily; avoid Hyper-V, WSL, Docker, and virtual adapter addresses.
5. Ensure both devices are on the same normal LAN/VLAN. Guest Wi-Fi often enables client/AP isolation.
6. Actually drive; menus and pauses normally produce no traffic.
7. If necessary, use Wireshark or `pktmon` to decide whether packets reach Windows at all.

If Wireshark sees packets but Python sees none, investigate Windows Firewall, another process owning the port, bind address, and Python/app permissions. If Wireshark sees no packets, investigate the FH6 target IP/port and network routing.

## 6. Optional Wireshark verification

Wireshark is not required. For deeper diagnosis:

1. Start Wireshark as appropriate and select the active Ethernet or Wi-Fi adapter—not a VPN, loopback, Hyper-V, WSL, or Docker adapter.
2. Start capture and use this display filter:

   ```text
   udp.dstport == 20440
   ```

3. Start FH6 and drive.
4. Confirm packets target the Windows PC LAN address and port 20440.
5. Inspect UDP payload length and compare it with the probe's observed-length table. Research predicts 324 payload bytes.

`udp.port == 20440` is a broader filter that includes either source or destination port.

## 7. Capture checklist

Run:

```powershell
python tools\udp_probe.py --port 20440 --capture captures\first-drive.fh6cap
```

For a useful parser-validation capture, record roughly one minute containing stationary idle, revving, acceleration, braking, full-left/right steering, gear shifts, a known approximate speed, pause/resume, and entering/leaving a race. A puddle and rumble strip are especially useful because documentation conflicts about the puddle fields.

Press `Ctrl+C`, keep the final summary, and provide `captures\first-drive.fh6cap` for the next milestone. Captures contain driving telemetry and world-position coordinates; treat them as private local data if that matters to you.

## Replay a capture

Replay uses localhost by default, so it can feed a telemetry service running on this PC without FH6 running:

```powershell
python tools\replay_capture.py captures\first-drive.fh6cap
```

Timing modes:

```powershell
# Half speed
python tools\replay_capture.py captures\first-drive.fh6cap --speed 0.5

# Original timing (the default)
python tools\replay_capture.py captures\first-drive.fh6cap --speed 1

# Twice as fast
python tools\replay_capture.py captures\first-drive.fh6cap --speed 2

# Send as fast as the local UDP stack accepts packets
python tools\replay_capture.py captures\first-drive.fh6cap --speed max
```

Choose a different destination when needed:

```powershell
python tools\replay_capture.py captures\first-drive.fh6cap --host 127.0.0.1 --port 20441 --speed 1
```

Only one process should own a given UDP listening port. To watch a replay with the diagnostic probe, use two PowerShell windows and a spare port:

PowerShell window 1:

```powershell
python tools\udp_probe.py --port 20441 --capture captures\replay-check.fh6cap
```

PowerShell window 2:

```powershell
python tools\replay_capture.py captures\first-drive.fh6cap --port 20441 --speed 1
```

Press `Ctrl+C` in the probe after replay completes. At original timing, its packet count, length distribution, and payload data should match the source. UDP itself does not guarantee delivery, so maximum-speed replay may overrun a slow receiver or a small socket buffer; use 1× for integrity checks.

The replay tool validates the entire file before transmitting, rejects malformed Base64 and length mismatches, preserves every payload byte, and schedules from absolute deadlines so send overhead does not accumulate as timing drift. The recorded sender IP and source port remain metadata; replay does not spoof them. The receiving application will see a new local source endpoint.

## Capture file format

`.fh6cap` is UTF-8 newline-delimited JSON (`fh6cap-jsonl`, version 1):

- line 1 is a header with format version, creation time, and bind endpoint;
- each following line is one packet with UTC receive time, Unix nanoseconds, source IP/port, reported length, and the exact UDP payload encoded as Base64.

Each line is flushed immediately so a Ctrl+C or later crash loses as little as practical. Payload bytes round-trip exactly; tests verify this. The format is intentionally simple enough to inspect in a text editor and will support the later replay tool.

The complete schema, validation rules, timing behavior, and compatibility policy are documented in [the capture format specification](docs/capture-format.md).

## Security note

Binding `0.0.0.0` accepts UDP on all PC interfaces permitted by the firewall. Keep the firewall profile Private and do not forward UDP 20440 on your router. The probe treats every datagram as untrusted bytes, performs no execution or parsing, limits each receive to the maximum UDP payload, and retains only bounded rate statistics plus counters. Capture files grow until you stop the probe, so monitor available disk space during very long captures.
