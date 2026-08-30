"""Build the portable one-file Windows tray executable."""

from __future__ import annotations

import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.name != "nt":
        raise SystemExit("The Windows executable must be built on Windows.")

    # Running this file directly puts tools/ on the import path, so add the repo root.
    sys.path.insert(0, str(ROOT))
    try:
        import PyInstaller.__main__
        from app.tray_icon import create_tray_image
    except ImportError as error:
        raise SystemExit(
            "Build dependencies are missing. Run: pip install -r requirements-build.txt"
        ) from error

    generated = ROOT / "build" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    icon_path = generated / "fh6-telemetry.ico"
    create_tray_image(256).save(
        icon_path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )

    static_dir = ROOT / "app" / "web" / "static"
    args = [
        str(ROOT / "app" / "tray.py"),
        "--name=FH6 Telemetry",
        "--onefile",
        "--windowed",
        "--clean",
        "--noconfirm",
        f"--paths={ROOT}",
        f"--icon={icon_path}",
        f"--version-file={ROOT / 'packaging' / 'windows_version_info.txt'}",
        f"--add-data={static_dir}{os.pathsep}app/web/static",
        "--hidden-import=pystray._win32",
        "--hidden-import=uvicorn.logging",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.http.h11_impl",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import=uvicorn.lifespan.on",
        "--exclude-module=IPython",
        "--exclude-module=matplotlib",
        "--exclude-module=numpy",
        "--exclude-module=pandas",
        "--exclude-module=scipy",
        "--exclude-module=notebook",
        "--exclude-module=jupyter",
        "--exclude-module=PyQt5",
        "--exclude-module=PyQt6",
        "--exclude-module=PySide6",
        "--exclude-module=gi",
        f"--distpath={ROOT / 'dist'}",
        f"--workpath={ROOT / 'build' / 'pyinstaller'}",
        f"--specpath={ROOT / 'build'}",
    ]
    PyInstaller.__main__.run(args)

    executable = ROOT / "dist" / "FH6 Telemetry.exe"
    if not executable.exists():
        raise SystemExit("PyInstaller finished without creating the executable.")
    size_mb = executable.stat().st_size / (1024 * 1024)
    print(f"Built {executable} ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
