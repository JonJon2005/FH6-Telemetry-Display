"""Human-editable JSON configuration with environment-variable overrides."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any

from app.config import Settings
from .paths import AppPaths


CONFIG_VERSION = 2


class ConfigError(ValueError):
    pass


def ensure_default_config(paths: AppPaths) -> None:
    if paths.config_file.exists():
        return
    # Write a temporary file first so a crash cannot leave half a config.
    payload = {"version": CONFIG_VERSION, **asdict(Settings())}
    temporary = paths.config_file.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, paths.config_file)


def load_settings(paths: AppPaths, *, save_migration: bool = True) -> Settings:
    # Settings.from_env handles the final override order and validation.
    defaults = _read_config(paths.config_file) if paths.config_file.exists() else {}
    if defaults.get("version") == 1:
        # Move old installs off the previous 8080 default without changing custom ports.
        if defaults.get("http_port") == 8080:
            defaults["http_port"] = 50415
        defaults["version"] = CONFIG_VERSION
        if save_migration:
            _write_config(paths.config_file, defaults)
    defaults.pop("version", None)
    return Settings.from_env(defaults)


def _read_config(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    if value.get("version", CONFIG_VERSION) not in (1, CONFIG_VERSION):
        raise ConfigError(f"Unsupported config version in {path}")
    return value


def _write_config(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
