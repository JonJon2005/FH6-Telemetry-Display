"""Runtime configuration for the telemetry diagnostic service."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


@dataclass(frozen=True, slots=True)
class Settings:
    udp_host: str = "0.0.0.0"
    udp_port: int = 20440
    http_host: str = "0.0.0.0"
    http_port: int = 50415
    telemetry_timeout_seconds: float = 2.0
    telemetry_publish_hz: float = 20.0
    debug_push_hz: float = 10.0
    websocket_send_timeout_seconds: float = 2.0
    max_websocket_clients: int = 32
    lan_ip_override: str | None = None
    recording_enabled: bool = True
    recording_hz: float = 5.0
    session_end_timeout_seconds: float = 10.0
    log_max_bytes: int = 5 * 1024 * 1024
    log_backup_count: int = 5

    @classmethod
    def from_env(cls, defaults: Mapping[str, object] | None = None) -> "Settings":
        # Environment values win over the config file and built-in defaults.
        source = defaults or {}
        return cls(
            udp_host=_text("FH6_UDP_HOST", source, "udp_host", "0.0.0.0"),
            udp_port=_port("FH6_UDP_PORT", source.get("udp_port", 20440)),
            http_host=_text("FH6_HTTP_HOST", source, "http_host", "0.0.0.0"),
            http_port=_port("FH6_HTTP_PORT", source.get("http_port", 50415)),
            telemetry_timeout_seconds=_positive_float("FH6_TELEMETRY_TIMEOUT", source.get("telemetry_timeout_seconds", 2.0)),
            telemetry_publish_hz=_bounded_float("FH6_TELEMETRY_PUBLISH_HZ", source.get("telemetry_publish_hz", 20.0), 1.0, 120.0),
            debug_push_hz=_positive_float("FH6_DEBUG_PUSH_HZ", source.get("debug_push_hz", 10.0)),
            websocket_send_timeout_seconds=_positive_float("FH6_WEBSOCKET_SEND_TIMEOUT", source.get("websocket_send_timeout_seconds", 2.0)),
            max_websocket_clients=_positive_int("FH6_MAX_WEBSOCKET_CLIENTS", source.get("max_websocket_clients", 32)),
            lan_ip_override=_optional_text("FH6_LAN_IP", source.get("lan_ip_override")),
            recording_enabled=_boolean("FH6_RECORDING_ENABLED", source.get("recording_enabled", True)),
            recording_hz=_bounded_float("FH6_RECORDING_HZ", source.get("recording_hz", 5.0), 0.2, 60.0),
            session_end_timeout_seconds=_positive_float("FH6_SESSION_END_TIMEOUT", source.get("session_end_timeout_seconds", 10.0)),
            log_max_bytes=_positive_int("FH6_LOG_MAX_BYTES", source.get("log_max_bytes", 5 * 1024 * 1024)),
            log_backup_count=_positive_int("FH6_LOG_BACKUP_COUNT", source.get("log_backup_count", 5)),
        )


def _port(name: str, default: object) -> int:
    value = int(os.getenv(name, str(default)))
    if not 0 <= value <= 65535:
        raise ValueError(f"{name} must be between 0 and 65535")
    return value


def _positive_float(name: str, default: object) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _bounded_float(name: str, default: object, minimum: float, maximum: float) -> float:
    value = _positive_float(name, default)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _positive_int(name: str, default: object) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _text(name: str, defaults: Mapping[str, object], key: str, fallback: str) -> str:
    return os.getenv(name, str(defaults.get(key, fallback)))


def _optional_text(name: str, default: object) -> str | None:
    value = os.getenv(name)
    if value is None:
        value = "" if default is None else str(default)
    return value.strip() or None


def _boolean(name: str, default: object) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")
