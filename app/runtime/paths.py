"""Platform-correct locations for data that must survive app upgrades."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys


APP_DIRECTORY_NAME = "FH6 Telemetry"


@dataclass(frozen=True, slots=True)
class AppPaths:
    base_dir: Path
    data_dir: Path
    logs_dir: Path
    exports_dir: Path
    config_file: Path
    database_file: Path
    lock_file: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        # FH6_HOME is handy for testing or using a custom drive.
        override = os.getenv("FH6_HOME")
        if override:
            return cls.from_base(Path(override).expanduser())
        if sys.platform == "win32":
            parent = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            base = parent / APP_DIRECTORY_NAME
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / APP_DIRECTORY_NAME
        else:
            parent = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            base = parent / "fh6-telemetry"
        return cls.from_base(base)

    @classmethod
    def from_base(cls, base_dir: Path) -> "AppPaths":
        base = base_dir.resolve()
        data = base / "data"
        return cls(
            base_dir=base,
            data_dir=data,
            logs_dir=base / "logs",
            exports_dir=base / "exports",
            config_file=base / "config.json",
            database_file=data / "telemetry.sqlite3",
            lock_file=base / "fh6-telemetry.lock",
        )

    def ensure(self) -> None:
        # Creating an existing folder is safe, so this can run every startup.
        for directory in (self.base_dir, self.data_dir, self.logs_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)
