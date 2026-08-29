from __future__ import annotations

import pytest

from app.config import Settings


def test_default_dashboard_port_is_unique() -> None:
    assert Settings().http_port == 50415


def test_phase6_environment_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FH6_TELEMETRY_PUBLISH_HZ", "30")
    monkeypatch.setenv("FH6_MAX_WEBSOCKET_CLIENTS", "12")
    monkeypatch.setenv("FH6_WEBSOCKET_SEND_TIMEOUT", "1.5")
    monkeypatch.setenv("FH6_LAN_IP", "192.168.50.8")
    settings = Settings.from_env()
    assert settings.telemetry_publish_hz == 30
    assert settings.max_websocket_clients == 12
    assert settings.websocket_send_timeout_seconds == 1.5
    assert settings.lan_ip_override == "192.168.50.8"


@pytest.mark.parametrize("value", ["0", "121"])
def test_publish_rate_rejects_unsafe_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("FH6_TELEMETRY_PUBLISH_HZ", value)
    with pytest.raises(ValueError, match="FH6_TELEMETRY_PUBLISH_HZ"):
        Settings.from_env()
