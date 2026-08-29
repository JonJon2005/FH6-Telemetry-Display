from __future__ import annotations

import json
import subprocess

import pytest

from app.config import Settings
from app.network import AdapterAddress, NetworkDiscovery, discover_lan_ipv4, startup_lines


def completed(records: list[dict[str, object]]) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], 0, json.dumps(records), "")


def test_windows_default_route_prefers_physical_lan_over_lower_metric_vpn() -> None:
    records = [
        {"ip_address": "10.8.0.2", "interface_alias": "My VPN", "interface_index": 8, "route_metric": 1, "interface_metric": 5, "hardware_interface": False},
        {"ip_address": "192.168.1.205", "interface_alias": "Ethernet", "interface_index": 4, "route_metric": 10, "interface_metric": 25, "hardware_interface": True},
    ]
    result = discover_lan_ipv4(platform="nt", runner=lambda command: completed(records))
    assert result.primary is not None
    assert result.primary.ip_address == "192.168.1.205"
    assert result.primary.interface_alias == "Ethernet"
    assert len(result.candidates) == 2


def test_two_physical_routes_use_lowest_combined_metric() -> None:
    records = [
        {"ip_address": "192.168.1.20", "interface_alias": "Wi-Fi", "interface_index": 6, "route_metric": 10, "interface_metric": 40, "hardware_interface": True},
        {"ip_address": "192.168.1.30", "interface_alias": "Ethernet", "interface_index": 4, "route_metric": 20, "interface_metric": 5, "hardware_interface": True},
    ]
    result = discover_lan_ipv4(platform="nt", runner=lambda command: completed(records))
    assert result.primary is not None
    assert result.primary.ip_address == "192.168.1.30"


def test_override_wins_and_rejects_unusable_addresses() -> None:
    result = discover_lan_ipv4("192.168.50.8")
    assert result.primary is not None
    assert result.primary.source == "override"
    assert result.primary.ip_address == "192.168.50.8"
    with pytest.raises(ValueError, match="not a usable"):
        discover_lan_ipv4("127.0.0.1")
    with pytest.raises(ValueError, match="IPv4"):
        discover_lan_ipv4("::1")


class FakeRouteSocket:
    def __init__(self, address: str) -> None:
        self.address = address
        self.closed = False

    def connect(self, target: tuple[str, int]) -> None:
        assert target == ("192.0.2.1", 9)

    def getsockname(self) -> tuple[str, int]:
        return self.address, 12345

    def close(self) -> None:
        self.closed = True


def test_socket_route_fallback_when_detailed_discovery_is_empty() -> None:
    route_socket = FakeRouteSocket("192.168.10.7")
    result = discover_lan_ipv4(
        platform="nt",
        runner=lambda command: completed([]),
        route_socket_factory=lambda: route_socket,  # type: ignore[arg-type]
    )
    assert result.primary is not None
    assert result.primary.ip_address == "192.168.10.7"
    assert result.primary.source == "socket-route-fallback"
    assert route_socket.closed
    assert any("fallback" in warning for warning in result.warnings)


def test_non_admin_route_table_fallback_recovers_adapter_name() -> None:
    route_output = """
Active Routes:
Network Destination        Netmask          Gateway       Interface  Metric
          0.0.0.0          0.0.0.0      192.168.1.1    192.168.1.205     25
          0.0.0.0          0.0.0.0         On-link          10.8.0.2      5
"""
    ipconfig_output = """
Ethernet adapter Ethernet:
   IPv4 Address. . . . . . . . . . . : 192.168.1.205
Unknown adapter My VPN:
   IPv4 Address. . . . . . . . . . . : 10.8.0.2
"""

    def runner(command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if command[0] == "powershell.exe":
            return subprocess.CompletedProcess(command, 1, "", "Access denied")
        if command[0] == "route.exe":
            return subprocess.CompletedProcess(command, 0, route_output, "")
        return subprocess.CompletedProcess(command, 0, ipconfig_output, "")

    result = discover_lan_ipv4(platform="nt", runner=runner)
    assert result.primary is not None
    assert result.primary.ip_address == "192.168.1.205"
    assert result.primary.interface_alias == "Ethernet"
    assert result.primary.source == "windows-route-table"
    assert result.warnings == ()


def test_endpoint_status_distinguishes_lan_and_loopback_binds() -> None:
    candidate = AdapterAddress("192.168.1.205", "Ethernet", 4, 10, 25, True, "test")
    discovery = NetworkDiscovery(candidate, (candidate,), ())
    status = discovery.endpoint_status(Settings())
    assert status["network_dashboard_url"] == "http://192.168.1.205:50415"
    assert status["local_dashboard_url"] == "http://localhost:50415"
    assert status["fh6_data_out_ip"] == "192.168.1.205"
    assert status["lan_accessible"] is True

    loopback = discovery.endpoint_status(Settings(http_host="127.0.0.1", udp_host="127.0.0.1"))
    assert loopback["network_dashboard_url"] is None
    assert loopback["fh6_data_out_ip"] is None
    assert len(loopback["warnings"]) == 2


def test_startup_output_contains_exact_dashboard_and_xbox_targets() -> None:
    candidate = AdapterAddress("192.168.1.205", "Ethernet", 4, 10, 25, True, "test")
    lines = startup_lines(Settings(), NetworkDiscovery(candidate, (candidate,), ()))
    output = "\n".join(lines)
    assert "Network: http://192.168.1.205:50415" in output
    assert "Adapter: Ethernet" in output
    assert "IP:   192.168.1.205" in output
    assert "Port: 20440" in output
