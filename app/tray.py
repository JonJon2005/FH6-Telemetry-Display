"""Windows tray entry point for the packaged FH6 Telemetry app."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import webbrowser

import pystray
import uvicorn

from app.config import Settings
from app.main import create_app
from app.network import NetworkDiscovery, discover_lan_ipv4
from app.runtime.config_file import ensure_default_config, load_settings, update_config
from app.runtime.paths import AppPaths
from app.runtime.startup import (
    application_command,
    is_run_at_startup_enabled,
    set_run_at_startup,
)
from app.tray_icon import create_tray_image


logger = logging.getLogger(__name__)
APP_NAME = "FH6 Telemetry"


def validate_port(value: str, label: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError(f"{label} must be a number") from error
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} must be between 1 and 65535")
    return port


class TrayApplication:
    def __init__(self, *, started_automatically: bool = False) -> None:
        self.started_automatically = started_automatically
        self.paths = AppPaths.discover()
        self.paths.ensure()
        ensure_default_config(self.paths)
        self.settings = load_settings(self.paths)
        self.network: NetworkDiscovery = discover_lan_ipv4(
            self.settings.lan_ip_override
        )
        self.endpoints = self.network.endpoint_status(self.settings)
        self.web_app = create_app(
            self.settings,
            self.network,
            announce=False,
            app_paths=self.paths,
            manage_runtime=True,
        )
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.web_app,
                host=self.settings.http_host,
                port=self.settings.http_port,
                log_config=None,
                access_log=False,
            )
        )
        self.server_thread: threading.Thread | None = None
        self.icon: pystray.Icon | None = None
        self._shutting_down = threading.Event()
        self._settings_lock = threading.Lock()
        self._settings_open = False

    @property
    def local_url(self) -> str:
        return str(
            self.endpoints["local_dashboard_url"]
            or f"http://localhost:{self.settings.http_port}"
        )

    @property
    def lan_url(self) -> str | None:
        value = self.endpoints["network_dashboard_url"]
        return str(value) if value else None

    def run(self) -> None:
        self._start_server()
        menu = pystray.Menu(
            pystray.MenuItem(self._menu_status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open dashboard", self.open_local),
            pystray.MenuItem("Open LAN dashboard", self.open_lan, enabled=self.lan_url is not None),
            pystray.MenuItem("Open debug page", self.open_debug),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Settings", self.show_settings, default=True),
            pystray.MenuItem("Exit", self.exit_app),
        )
        self.icon = pystray.Icon(
            "fh6_telemetry",
            create_tray_image(),
            APP_NAME,
            menu,
        )
        try:
            self.icon.run(setup=self._on_tray_ready)
        finally:
            self.shutdown()

    def _start_server(self) -> None:
        self.server_thread = threading.Thread(
            target=self.server.run,
            name="fh6-web-server",
            daemon=True,
        )
        self.server_thread.start()
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline:
            if self.server.started:
                return
            if not self.server_thread.is_alive():
                break
            time.sleep(0.05)
        raise RuntimeError(
            f"Could not start the dashboard on TCP port {self.settings.http_port}. "
            "Another copy or another app may already be using it."
        )

    def _on_tray_ready(self, icon: pystray.Icon) -> None:
        icon.visible = True
        if not self.started_automatically:
            icon.notify(
                f"Running on TCP {self.settings.http_port}. Click the tray icon for settings.",
                APP_NAME,
            )

    def _menu_status(self, _: pystray.MenuItem) -> str:
        return f"Dashboard {self.settings.http_port}  |  FH6 UDP {self.settings.udp_port}"

    def open_local(self, *_: object) -> None:
        webbrowser.open(self.local_url)

    def open_lan(self, *_: object) -> None:
        if self.lan_url:
            webbrowser.open(self.lan_url)

    def open_debug(self, *_: object) -> None:
        webbrowser.open(f"{self.local_url}/debug")

    def show_settings(self, *_: object) -> None:
        with self._settings_lock:
            if self._settings_open:
                return
            self._settings_open = True
        threading.Thread(
            target=self._settings_window,
            name="fh6-settings-window",
            daemon=True,
        ).start()

    def _settings_window(self) -> None:
        window: tk.Tk | None = None
        try:
            window = tk.Tk()
            window.title(f"{APP_NAME} Settings")
            window.geometry("520x545")
            window.resizable(False, False)
            window.configure(bg="#0d0f12")

            body = tk.Frame(window, bg="#0d0f12", padx=28, pady=24)
            body.pack(fill="both", expand=True)
            tk.Label(
                body, text=APP_NAME, bg="#0d0f12", fg="#f5f7fa",
                font=("Segoe UI Semibold", 20), anchor="w",
            ).pack(fill="x")
            tk.Label(
                body, text="Runs quietly in the Windows notification area.",
                bg="#0d0f12", fg="#9ba3ad", font=("Segoe UI", 10), anchor="w",
            ).pack(fill="x", pady=(2, 18))

            status_text = tk.StringVar(value=self._service_status())
            status = tk.Label(
                body, textvariable=status_text, bg="#171a1f", fg="#f2b200",
                font=("Segoe UI Semibold", 10), anchor="w", padx=14, pady=10,
            )
            status.pack(fill="x", pady=(0, 16))

            self._info_row(body, "Local dashboard", self.local_url)
            self._info_row(body, "LAN dashboard", self.lan_url or "No LAN address detected")
            target_ip = str(self.endpoints["fh6_data_out_ip"] or "Not detected")
            self._info_row(body, "FH6 Data Out", f"{target_ip}  /  UDP {self.settings.udp_port}")

            ports = tk.Frame(body, bg="#0d0f12")
            ports.pack(fill="x", pady=(18, 10))
            http_value = tk.StringVar(value=str(self.settings.http_port))
            udp_value = tk.StringVar(value=str(self.settings.udp_port))
            self._port_field(ports, "Dashboard TCP port", http_value, 0)
            self._port_field(ports, "FH6 UDP port", udp_value, 1)

            startup_value = tk.BooleanVar(value=is_run_at_startup_enabled())
            tk.Checkbutton(
                body,
                text="Run FH6 Telemetry when I sign in",
                variable=startup_value,
                bg="#0d0f12",
                fg="#d9dee5",
                activebackground="#0d0f12",
                activeforeground="#f5f7fa",
                selectcolor="#20242a",
                font=("Segoe UI", 10),
                anchor="w",
            ).pack(fill="x", pady=(8, 16))

            links = tk.Frame(body, bg="#0d0f12")
            links.pack(fill="x", pady=(0, 12))
            self._button(links, "Open local", self.open_local).pack(side="left")
            lan_button = self._button(links, "Open LAN", self.open_lan)
            lan_button.pack(side="left", padx=8)
            if self.lan_url is None:
                lan_button.configure(state="disabled")
            self._button(links, "Debug", self.open_debug).pack(side="left")

            def save_and_restart() -> None:
                try:
                    http_port = validate_port(http_value.get(), "Dashboard port")
                    udp_port = validate_port(udp_value.get(), "FH6 UDP port")
                    update_config(
                        self.paths,
                        {"http_port": http_port, "udp_port": udp_port},
                    )
                    set_run_at_startup(startup_value.get())
                except (OSError, ValueError) as error:
                    messagebox.showerror(APP_NAME, str(error), parent=window)
                    return
                window.destroy()
                threading.Thread(
                    target=self.shutdown,
                    kwargs={"restart": True},
                    name="fh6-restart",
                    daemon=True,
                ).start()

            footer = tk.Frame(body, bg="#0d0f12")
            footer.pack(fill="x", side="bottom")
            self._button(footer, "Close", window.destroy, quiet=True).pack(side="right")
            self._button(footer, "Save & restart", save_and_restart, accent=True).pack(
                side="right", padx=(0, 8)
            )

            def refresh_status() -> None:
                if window is not None and window.winfo_exists():
                    status_text.set(self._service_status())
                    window.after(1000, refresh_status)

            window.after(1000, refresh_status)
            window.protocol("WM_DELETE_WINDOW", window.destroy)
            window.mainloop()
        finally:
            with self._settings_lock:
                self._settings_open = False

    def _service_status(self) -> str:
        service = self.web_app.state.service
        if service.state.listener_status == "error":
            return f"UDP ERROR  •  {service.state.listener_error or 'Could not listen'}"
        connected = bool(service.state.realtime_snapshot()["connection"]["connected"])  # type: ignore[index]
        if connected:
            return f"LIVE TELEMETRY  •  TCP {self.settings.http_port}  •  UDP {self.settings.udp_port}"
        return f"RUNNING — WAITING FOR FH6  •  TCP {self.settings.http_port}  •  UDP {self.settings.udp_port}"

    @staticmethod
    def _info_row(parent: tk.Widget, name: str, value: str) -> None:
        row = tk.Frame(parent, bg="#0d0f12")
        row.pack(fill="x", pady=3)
        tk.Label(
            row, text=name, width=18, bg="#0d0f12", fg="#7f8791",
            font=("Segoe UI", 9), anchor="w",
        ).pack(side="left")
        tk.Label(
            row, text=value, bg="#0d0f12", fg="#e7eaf0",
            font=("Consolas", 9), anchor="w",
        ).pack(side="left")

    @staticmethod
    def _port_field(parent: tk.Widget, label: str, value: tk.StringVar, column: int) -> None:
        frame = tk.Frame(parent, bg="#0d0f12")
        frame.grid(row=0, column=column, sticky="ew", padx=(0, 10) if column == 0 else (10, 0))
        parent.grid_columnconfigure(column, weight=1)
        tk.Label(
            frame, text=label, bg="#0d0f12", fg="#9ba3ad",
            font=("Segoe UI", 9), anchor="w",
        ).pack(fill="x", pady=(0, 5))
        tk.Entry(
            frame, textvariable=value, bg="#171a1f", fg="#f5f7fa",
            insertbackground="#f5f7fa", relief="flat", font=("Consolas", 11),
        ).pack(fill="x", ipady=7)

    @staticmethod
    def _button(
        parent: tk.Widget,
        text: str,
        command,
        *,
        accent: bool = False,
        quiet: bool = False,
    ) -> tk.Button:
        background = "#f2b200" if accent else ("#0d0f12" if quiet else "#20242a")
        foreground = "#0d0f12" if accent else "#f5f7fa"
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=foreground,
            activebackground="#dca300" if accent else "#2b3038",
            activeforeground=foreground,
            relief="flat",
            cursor="hand2",
            padx=14,
            pady=8,
            font=("Segoe UI Semibold", 9),
        )

    def exit_app(self, *_: object) -> None:
        threading.Thread(target=self.shutdown, name="fh6-exit", daemon=True).start()

    def shutdown(self, *, restart: bool = False) -> None:
        if self._shutting_down.is_set():
            return
        self._shutting_down.set()
        self.server.should_exit = True
        if self.server_thread is not None and self.server_thread is not threading.current_thread():
            self.server_thread.join(timeout=12)
        if self.icon is not None:
            self.icon.stop()
        if restart:
            subprocess.Popen(application_command(), close_fds=True)


def _show_fatal_error(error: BaseException) -> None:
    message = f"FH6 Telemetry could not start.\n\n{error}"
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FH6 Telemetry in the Windows tray")
    parser.add_argument("--startup", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        TrayApplication(started_automatically=args.startup).run()
    except BaseException as error:
        logger.exception("Tray app failed")
        _show_fatal_error(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
