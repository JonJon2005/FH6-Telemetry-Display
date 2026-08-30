from __future__ import annotations

import json
import sys

import pytest

from app.runtime.config_file import ensure_default_config, load_settings, update_config
from app.runtime.paths import AppPaths
from app.runtime.startup import application_command, quoted_application_command
from app.tray import validate_port
from app.tray_icon import create_tray_image


def test_tray_port_validation() -> None:
    assert validate_port("50415", "Dashboard port") == 50415
    with pytest.raises(ValueError, match="must be a number"):
        validate_port("fast", "Dashboard port")
    with pytest.raises(ValueError, match="between 1 and 65535"):
        validate_port("70000", "Dashboard port")


def test_tray_config_update_preserves_other_settings(tmp_path) -> None:
    paths = AppPaths.from_base(tmp_path / "profile")
    paths.ensure()
    ensure_default_config(paths)

    update_config(paths, {"http_port": 51015, "udp_port": 21040})

    settings = load_settings(paths)
    assert settings.http_port == 51015
    assert settings.udp_port == 21040
    assert settings.recording_enabled is True
    assert json.loads(paths.config_file.read_text(encoding="utf-8"))["version"] == 2


def test_source_startup_command_is_quoted(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    command = application_command()
    assert command[1:] == ["-m", "app.tray", "--startup"]
    assert str(sys.executable) in quoted_application_command()


def test_tray_icon_has_expected_sizes() -> None:
    assert create_tray_image().size == (64, 64)
    assert create_tray_image(256).size == (256, 256)
