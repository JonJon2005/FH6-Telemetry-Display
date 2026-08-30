"""Console plus bounded rotating-file logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import sys

from app.config import Settings
from .paths import AppPaths


def configure_logging(paths: AppPaths, settings: Settings) -> None:
    paths.ensure()
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    for handler in list(root.handlers):
        # Replacing our old handlers prevents duplicate lines after a restart.
        if getattr(handler, "_fh6_managed", False):
            root.removeHandler(handler)
            handler.close()

    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console._fh6_managed = True  # type: ignore[attr-defined]
        root.addHandler(console)

    file_handler = RotatingFileHandler(
        # Old files are rotated so logs cannot grow forever.
        paths.logs_dir / "fh6-telemetry.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler._fh6_managed = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers.clear()
        logging.getLogger(name).propagate = True
