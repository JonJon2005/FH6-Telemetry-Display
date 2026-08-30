"""Windows run-at-sign-in setting for the tray app."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "FH6 Telemetry"


def application_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--startup"]
    return [str(Path(sys.executable).resolve()), "-m", "app.tray", "--startup"]


def quoted_application_command() -> str:
    return subprocess.list2cmdline(application_command())


def is_run_at_startup_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE_NAME)
    except FileNotFoundError:
        return False
    return str(value) == quoted_application_command()


def set_run_at_startup(enabled: bool) -> None:
    if os.name != "nt":
        raise OSError("Run at startup is only available on Windows")
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_KEY, access=winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key, RUN_VALUE_NAME, 0, winreg.REG_SZ, quoted_application_command()
            )
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
