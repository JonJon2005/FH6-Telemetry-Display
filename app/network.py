"""Windows-first LAN IPv4 discovery and advertised endpoint selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import ipaddress
import json
import os
import re
import socket
import subprocess
from typing import Callable, Sequence

from app.config import Settings


_VIRTUAL_MARKERS = (
    # These adapters usually cannot receive packets from the Xbox.
    "bluetooth",
    "docker",
    "hyper-v",
    "loopback",
    "tailscale",
    "tap-",
    "vethernet",
    "virtual",
    "vpn",
    "wireguard",
    "wsl",
    "zerotier",
)

_WINDOWS_DISCOVERY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$results = @()
$routes = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' |
    Where-Object { $_.State -eq 'Alive' } |
    Sort-Object RouteMetric
foreach ($route in $routes) {
    $ipInterface = Get-NetIPInterface -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
    $adapter = Get-NetAdapter -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue
    $addresses = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue |
        Where-Object { $_.AddressState -eq 'Preferred' }
    foreach ($address in $addresses) {
        $results += [PSCustomObject]@{
            ip_address = $address.IPAddress
            interface_alias = $address.InterfaceAlias
            interface_index = $route.InterfaceIndex
            route_metric = $route.RouteMetric
            interface_metric = if ($null -ne $ipInterface) { $ipInterface.InterfaceMetric } else { 99999 }
            hardware_interface = if ($null -ne $adapter) { [bool]$adapter.HardwareInterface } else { $null }
            adapter_status = if ($null -ne $adapter) { [string]$adapter.Status } else { $null }
        }
    }
}
@($results) | ConvertTo-Json -Compress
""".strip()


@dataclass(frozen=True, slots=True)
class AdapterAddress:
    ip_address: str
    interface_alias: str
    interface_index: int | None
    route_metric: int | None
    interface_metric: int | None
    hardware_interface: bool | None
    source: str

    @property
    def is_virtual(self) -> bool:
        alias = self.interface_alias.casefold()
        return self.hardware_interface is False or any(marker in alias for marker in _VIRTUAL_MARKERS)

    @property
    def effective_metric(self) -> int:
        return (self.route_metric or 0) + (self.interface_metric or 0)


@dataclass(frozen=True, slots=True)
class NetworkDiscovery:
    primary: AdapterAddress | None
    candidates: tuple[AdapterAddress, ...]
    warnings: tuple[str, ...]

    def endpoint_status(self, settings: Settings) -> dict[str, object]:
        primary_ip = self.primary.ip_address if self.primary else None
        local_url = (
            f"http://localhost:{settings.http_port}"
            if settings.http_host in ("0.0.0.0", "127.0.0.1", "localhost")
            else None
        )
        if settings.http_host == "0.0.0.0":
            network_host = primary_ip
        elif _usable_non_loopback(settings.http_host):
            network_host = settings.http_host
        else:
            network_host = None
        network_url = f"http://{network_host}:{settings.http_port}" if network_host else None

        if settings.udp_host == "0.0.0.0":
            fh6_target = primary_ip
        elif _usable_non_loopback(settings.udp_host):
            fh6_target = settings.udp_host
        else:
            fh6_target = None

        warnings = list(self.warnings)
        if settings.http_host in ("127.0.0.1", "localhost"):
            warnings.append("HTTP is bound to loopback; other LAN devices cannot open the dashboard.")
        if settings.udp_host in ("127.0.0.1", "localhost"):
            warnings.append("UDP is bound to loopback; an Xbox cannot send telemetry to it.")
        if not primary_ip:
            warnings.append("No usable LAN IPv4 address was detected; set FH6_LAN_IP explicitly.")

        return {
            "primary_ip": primary_ip,
            "interface_alias": self.primary.interface_alias if self.primary else None,
            "interface_index": self.primary.interface_index if self.primary else None,
            "discovery_source": self.primary.source if self.primary else None,
            "local_dashboard_url": local_url,
            "network_dashboard_url": network_url,
            "fh6_data_out_ip": fh6_target,
            "fh6_data_out_port": settings.udp_port,
            "http_bind": f"{settings.http_host}:{settings.http_port}",
            "udp_bind": f"{settings.udp_host}:{settings.udp_port}",
            "lan_accessible": network_url is not None,
            "candidates": [asdict(candidate) | {"is_virtual": candidate.is_virtual} for candidate in self.candidates],
            "warnings": list(dict.fromkeys(warnings)),
        }


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def discover_lan_ipv4(
    override: str | None = None,
    *,
    platform: str | None = None,
    runner: Runner | None = None,
    route_socket_factory: Callable[[], socket.socket] | None = None,
) -> NetworkDiscovery:
    """Select the preferred physical/default-route IPv4 without DNS guessing."""
    if override:
        address = _validated_address(override)
        candidate = AdapterAddress(address, "explicit FH6_LAN_IP", None, 0, 0, None, "override")
        warnings = () if _is_private_lan(address) else ("FH6_LAN_IP is not an RFC1918 private address; verify it before sharing the URL.",)
        return NetworkDiscovery(candidate, (candidate,), warnings)

    system = os.name if platform is None else platform
    errors: list[str] = []
    candidates: list[AdapterAddress] = []
    if system == "nt":
        # Try the detailed Windows route info first, then older commands.
        try:
            candidates = _windows_candidates(runner or _run_command)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append(f"Detailed Windows adapter discovery unavailable: {str(error).splitlines()[0]}")
        if not candidates:
            try:
                candidates = _route_print_candidates(runner or _run_command)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                errors.append(f"Windows route-table fallback failed: {str(error).splitlines()[0]}")
            if candidates:
                # The fallback worked, so the first warning no longer matters.
                errors.clear()

    if not candidates:
        fallback = _socket_route_candidate(route_socket_factory)
        if fallback is not None:
            candidates.append(fallback)
            errors.append("Using socket-route fallback because detailed adapter discovery was unavailable.")

    candidates = _deduplicate(candidates)
    candidates.sort(key=_candidate_rank)
    primary = candidates[0] if candidates else None
    if primary and primary.is_virtual:
        errors.append(f"The preferred route is a virtual/VPN-like adapter ({primary.interface_alias}); set FH6_LAN_IP if this is wrong.")
    return NetworkDiscovery(primary, tuple(candidates), tuple(errors))


def startup_lines(settings: Settings, network: NetworkDiscovery) -> list[str]:
    status = network.endpoint_status(settings)
    local = status["local_dashboard_url"] or "unavailable with current HTTP bind"
    lan = status["network_dashboard_url"] or "not detected / not LAN-bound"
    target = status["fh6_data_out_ip"] or "set FH6_LAN_IP"
    interface = status["interface_alias"] or "unknown"
    lines = [
        "FH6 Telemetry running",
        "",
        "UDP:",
        f"  {status['udp_bind']}",
        "",
        "Dashboard:",
        f"  Local:   {local}",
        f"  Network: {lan}",
        f"  Adapter: {interface}",
        "",
        "Configure FH6 Data Out:",
        f"  IP:   {target}",
        f"  Port: {settings.udp_port}",
        "",
        f"Telemetry WebSocket: {settings.telemetry_publish_hz:g} Hz",
    ]
    for warning in status["warnings"]:
        lines.append(f"WARNING: {warning}")
    return lines


def _run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
        creationflags=creation_flags,
    )


def _windows_candidates(runner: Runner) -> list[AdapterAddress]:
    completed = runner(("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _WINDOWS_DISCOVERY_SCRIPT))
    if completed.returncode != 0:
        raise OSError(completed.stderr.strip() or f"PowerShell exited {completed.returncode}")
    if not completed.stdout.strip():
        return []
    decoded = json.loads(completed.stdout.lstrip("\ufeff"))
    records = decoded if isinstance(decoded, list) else [decoded]
    candidates: list[AdapterAddress] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            address = _validated_address(str(record["ip_address"]))
        except (KeyError, ValueError):
            continue
        candidates.append(AdapterAddress(
            address,
            str(record.get("interface_alias") or "unknown adapter"),
            _optional_int(record.get("interface_index")),
            _optional_int(record.get("route_metric")),
            _optional_int(record.get("interface_metric")),
            record.get("hardware_interface") if isinstance(record.get("hardware_interface"), bool) else None,
            "windows-default-route",
        ))
    return candidates


def _route_print_candidates(runner: Runner) -> list[AdapterAddress]:
    route_result = runner(("route.exe", "PRINT", "-4"))
    if route_result.returncode != 0:
        raise OSError(route_result.stderr.strip() or f"route.exe exited {route_result.returncode}")
    ipconfig_result = runner(("ipconfig.exe",))
    aliases = _ipconfig_aliases(ipconfig_result.stdout) if ipconfig_result.returncode == 0 else {}
    pattern = re.compile(
        r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+\S+\s+(\d{1,3}(?:\.\d{1,3}){3})\s+(\d+)\s*$",
        re.MULTILINE,
    )
    candidates: list[AdapterAddress] = []
    for match in pattern.finditer(route_result.stdout):
        try:
            address = _validated_address(match.group(1))
        except ValueError:
            continue
        candidates.append(AdapterAddress(
            address,
            aliases.get(address, "Windows default IPv4 route"),
            None,
            int(match.group(2)),
            0,
            None,
            "windows-route-table",
        ))
    return candidates


def _ipconfig_aliases(output: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    current = "unknown adapter"
    header = re.compile(r"^\S.*?adapter\s+(.+):\s*$", re.IGNORECASE)
    address = re.compile(r"IPv4[^:]*:\s*(\d{1,3}(?:\.\d{1,3}){3})", re.IGNORECASE)
    for line in output.splitlines():
        header_match = header.match(line)
        if header_match:
            current = header_match.group(1).strip()
            continue
        address_match = address.search(line)
        if address_match:
            aliases[address_match.group(1)] = current
    return aliases


def _socket_route_candidate(factory: Callable[[], socket.socket] | None) -> AdapterAddress | None:
    maker = factory or (lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM))
    route_socket = maker()
    try:
        route_socket.connect(("192.0.2.1", 9))
        address = _validated_address(str(route_socket.getsockname()[0]))
    except (OSError, ValueError):
        return None
    finally:
        route_socket.close()
    return AdapterAddress(address, "default route (adapter name unavailable)", None, None, None, None, "socket-route-fallback")


def _candidate_rank(candidate: AdapterAddress) -> tuple[int, int, int]:
    # Prefer a real private-network adapter with the lowest route cost.
    return (1 if candidate.is_virtual else 0, 0 if _is_private_lan(candidate.ip_address) else 1, candidate.effective_metric)


def _deduplicate(candidates: list[AdapterAddress]) -> list[AdapterAddress]:
    unique: dict[str, AdapterAddress] = {}
    for candidate in candidates:
        unique.setdefault(candidate.ip_address, candidate)
    return list(unique.values())


def _validated_address(value: str) -> str:
    address = ipaddress.ip_address(value.strip())
    if not isinstance(address, ipaddress.IPv4Address):
        raise ValueError("address must be IPv4")
    if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified:
        raise ValueError(f"{address} is not a usable LAN IPv4 address")
    return str(address)


def _usable_non_loopback(value: str) -> bool:
    try:
        _validated_address(value)
    except ValueError:
        return False
    return True


def _is_private_lan(value: str) -> bool:
    address = ipaddress.IPv4Address(value)
    return any(address in network for network in (
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
    ))


def _optional_int(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
