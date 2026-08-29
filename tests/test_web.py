from __future__ import annotations

import socket

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.network import AdapterAddress, NetworkDiscovery


TEST_ADAPTER = AdapterAddress("192.168.1.205", "Ethernet", 4, 10, 25, True, "test")
TEST_NETWORK = NetworkDiscovery(TEST_ADAPTER, (TEST_ADAPTER,), ())


def make_app(settings: Settings):
    return create_app(settings, TEST_NETWORK, announce=False)


def test_debug_page_api_health_and_redirect() -> None:
    app = make_app(Settings(udp_host="127.0.0.1", udp_port=0, debug_push_hz=100))
    with TestClient(app) as client:
        redirect = client.get("/", follow_redirects=False)
        assert redirect.status_code in (302, 307)
        assert redirect.headers["location"] == "/dashboard"
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert "FH6 Live Dashboard" in dashboard.text
        assert "Driver inputs" in dashboard.text
        assert "G meter" in dashboard.text
        assert "eyebrow" not in dashboard.text.lower()
        dashboard_css = client.get("/static/dashboard.css")
        assert dashboard_css.status_code == 200
        assert "gradient" not in dashboard_css.text.lower()
        assert "orientation:landscape" in dashboard_css.text
        assert "max-width:680px" in dashboard_css.text
        dashboard_js = client.get("/static/dashboard.js")
        assert dashboard_js.status_code == 200
        assert "/ws/telemetry" in dashboard_js.text
        page = client.get("/debug")
        assert page.status_code == 200
        assert "FH6 Telemetry Diagnostics" in page.text
        assert 'href="/dashboard"' in page.text
        assert "Main dashboard" in page.text
        assert "eyebrow" not in page.text.lower()
        assert client.get("/static/debug.js").status_code == 200
        debug_css = client.get("/static/debug.css")
        assert debug_css.status_code == 200
        assert "gradient" not in debug_css.text.lower()
        assert "backdrop-filter" not in debug_css.text.lower()
        snapshot = client.get("/api/debug").json()
        assert snapshot["listener"]["status"] == "listening"
        assert snapshot["connection"]["connected"] is False
        health = client.get("/health").json()
        assert health["status"] == "ok"
        assert health["service_running"] is True
        assert health["broadcast_hz"] == 20
        assert health["network"]["primary_ip"] == "192.168.1.205"
        assert client.get("/api/network").json()["network_dashboard_url"] == "http://192.168.1.205:50415"


def test_debug_websocket_sends_initial_snapshot() -> None:
    app = make_app(Settings(udp_host="127.0.0.1", udp_port=0, debug_push_hz=100))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/debug") as websocket:
            snapshot = websocket.receive_json()
            assert snapshot["parser"]["version"] == "fh6-324-v1"
            assert snapshot["listener"]["status"] == "listening"


def test_actual_udp_datagram_reaches_realtime_api_and_websocket() -> None:
    from tests.test_validation import valid_packet

    app = make_app(Settings(udp_host="127.0.0.1", udp_port=0, telemetry_publish_hz=100))
    with TestClient(app) as client:
        port = int(app.state.telemetry.bound_address.rsplit(":", 1)[1])
        with client.websocket_connect("/ws/telemetry") as websocket:
            initial = websocket.receive_json()
            assert initial["schema_version"] == 1
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sender.sendto(bytes(valid_packet()), ("127.0.0.1", port))
            finally:
                sender.close()
            for _ in range(20):
                live = websocket.receive_json()
                if live["sequence"] >= 1:
                    break
            assert live["connection"]["connected"] is True
            assert live["telemetry"]["inputs"]["gear"]["label"] == "3"
            api = client.get("/api/telemetry").json()
            assert api["connection"]["valid_packets"] == 1


def test_two_realtime_clients_receive_same_latest_sequence() -> None:
    from tests.test_validation import valid_packet

    app = make_app(Settings(udp_host="127.0.0.1", udp_port=0, telemetry_publish_hz=100))
    with TestClient(app) as client:
        port = int(app.state.telemetry.bound_address.rsplit(":", 1)[1])
        with client.websocket_connect("/ws/telemetry") as first:
            first.receive_json()
            with client.websocket_connect("/ws/telemetry") as second:
                second.receive_json()
                sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sender.sendto(bytes(valid_packet()), ("127.0.0.1", port))
                finally:
                    sender.close()
                first_live = first.receive_json()
                while first_live["sequence"] < 1:
                    first_live = first.receive_json()
                second_live = second.receive_json()
                while second_live["sequence"] < 1:
                    second_live = second.receive_json()
                assert first_live["sequence"] == second_live["sequence"] == 1


def test_udp_bind_failure_keeps_diagnostic_http_alive() -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    occupied.bind(("127.0.0.1", 0))
    port = occupied.getsockname()[1]
    app = make_app(Settings(udp_host="127.0.0.1", udp_port=port))
    try:
        with TestClient(app) as client:
            health = client.get("/health").json()
            assert health["status"] == "degraded"
            assert health["udp_listener"] == "error"
            assert health["udp_error"]
            assert client.get("/debug").status_code == 200
    finally:
        occupied.close()


def test_combined_websocket_client_limit_is_enforced() -> None:
    app = make_app(Settings(udp_host="127.0.0.1", udp_port=0, max_websocket_clients=1))
    with TestClient(app) as client:
        with client.websocket_connect("/ws/telemetry") as first:
            first.receive_json()
            with client.websocket_connect("/ws/debug") as rejected:
                with pytest.raises(WebSocketDisconnect) as error:
                    rejected.receive_json()
                assert error.value.code == 1013
