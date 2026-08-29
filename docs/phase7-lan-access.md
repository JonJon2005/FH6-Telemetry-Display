# Phase 7: Windows LAN discovery and dashboard access

Phase 7 makes the service advertise the correct addresses for two different consumers:

- FH6 on Xbox sends **UDP** to the Windows PC's LAN IPv4 on port `20440`.
- Phones, tablets, and other PCs open the **HTTP** dashboard at that LAN IPv4 on port `50415`.

The primary visible page is now the Phase 8 driving dashboard. The diagnostic dashboard remains available at `/debug`.

## Startup output

Run:

```powershell
python -m app.main
```

On the current development PC, startup produces the equivalent of:

```text
FH6 Telemetry running

UDP:
  0.0.0.0:20440

Dashboard:
  Local:   http://localhost:50415
  Network: http://192.168.1.205:50415
  Adapter: Ethernet

Configure FH6 Data Out:
  IP:   192.168.1.205
  Port: 20440

Telemetry WebSocket: 20 Hz
```

Use the addresses printed by your own startup. They may change when the router assigns a new address.

## Open it from another device

1. Leave `python -m app.main` running on Windows.
2. Connect the phone/tablet/computer to the same normal home LAN as the Windows PC.
3. Open the printed **Network** URL, including `:50415`.
4. If the page does not open, allow inbound TCP `50415` on the Windows **Private** firewall profile as documented in the README.

Do not use `localhost` or `127.0.0.1` on another device; those refer to that device itself.

The service binds HTTP and UDP to `0.0.0.0` by default, so Windows can receive them through the selected Ethernet or Wi-Fi interface. It does not configure the router, UPnP, or internet exposure.

## How selection works

Discovery runs once during application startup:

1. On Windows, inspect live IPv4 default routes and their interfaces.
2. Prefer an active hardware interface over aliases resembling VPN, Hyper-V, WSL, Docker, Tailscale, WireGuard, TAP, Bluetooth, loopback, or other tunnels.
3. Prefer RFC1918 LAN addresses and the lowest combined route/interface metric.
4. If detailed Windows adapter metadata is unavailable, parse the non-admin Windows IPv4 route table and map its address through `ipconfig`.
5. If that is also unavailable, ask the operating system which local address its default IPv4 route would use.

Link-local `169.254.x.x`, loopback, multicast, unspecified, and IPv6 addresses are never advertised as the Xbox target.

The selected IP, adapter, discovery source, considered candidates, URLs, and warnings are available at:

```text
http://localhost:50415/api/network
```

They also appear in `/health`, `/api/debug`, and the Connection panel on `/debug`.

## Override an ambiguous route

VPN full-tunnel configurations or unusual VLANs may make the operating-system default route unsuitable for the Xbox. Set the known Windows LAN IPv4 before starting:

```powershell
$env:FH6_LAN_IP = "192.168.1.205"
python -m app.main
```

The value must be a usable IPv4 address. Loopback, link-local, unspecified, multicast, and IPv6 values fail startup rather than being advertised incorrectly.

Remove the override from the current PowerShell session with:

```powershell
Remove-Item Env:FH6_LAN_IP
```

This override changes the advertised address and Xbox instructions. It does not assign an IP to Windows or change routing.

## Bind configuration warnings

Defaults are:

```text
FH6_HTTP_HOST=0.0.0.0
FH6_HTTP_PORT=50415
FH6_UDP_HOST=0.0.0.0
FH6_UDP_PORT=20440
```

Binding HTTP to `127.0.0.1` makes the dashboard local-only. Binding UDP to `127.0.0.1` prevents an Xbox from reaching it. `/api/network` reports both conditions explicitly.

## Troubleshooting another device

- Confirm the other device uses the printed Network URL, not the Xbox UDP port.
- Confirm Windows reports the network profile as Private.
- Confirm inbound TCP `50415` and UDP `20440` are permitted on the Private profile.
- Check that the phone is not on guest Wi-Fi with client isolation.
- Check that Xbox, Windows, and the browser device are on the same LAN/VLAN.
- Temporarily disconnect a VPN or use `FH6_LAN_IP` if it changes the selected route.
- Open `/api/network` locally and verify `primary_ip`, `interface_alias`, `http_bind`, and `lan_accessible`.
- Remember that FH6 telemetry may stop in menus and while paused; that does not prevent the webpage itself from loading.

## Verification result

On the development Windows PC, discovery ignored Tailscale, NordVPN TAP, Bluetooth, loopback, and tunnel interfaces and selected `Ethernet` at `192.168.1.205`. A temporary service bound to `0.0.0.0` was successfully reached through both `127.0.0.1` and `192.168.1.205`; the LAN `/debug` request returned HTTP 200.
