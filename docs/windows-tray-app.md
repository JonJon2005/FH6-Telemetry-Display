# Windows tray application

`FH6 Telemetry.exe` is a portable, one-file Windows application. It does not
need Python and does not need an installer. Double-click it, then use the yellow
tachometer icon in the Windows notification area.

Left-clicking the icon opens Settings. Right-clicking shows quick actions for
the local dashboard, LAN dashboard, debug page, Settings, and Exit. The window
shows the dashboard TCP port, FH6 UDP port, detected Xbox target IP, and live
telemetry status.

The **Run FH6 Telemetry when I sign in** option adds the current executable to
the current user's Windows startup apps. It does not require administrator
access. If the executable is moved later, turn the option off and on again to
save its new location.

Port changes are written to `%LOCALAPPDATA%\FH6 Telemetry\config.json` and the
app restarts itself. Exiting normally finalizes the current driving session.

## Build locally

From PowerShell on Windows:

```powershell
python -m pip install -r requirements-build.txt
python -m pytest -q
python tools\build_windows.py
```

The result is `dist\FH6 Telemetry.exe`. GitHub Actions also builds a fresh
artifact after a push to `main`.

## Sharing

Upload the executable to a GitHub Release rather than committing it to the
repository. Windows may show a SmartScreen warning until releases are signed
with a trusted code-signing certificate. The app never bypasses that warning.

LAN access can still require a Windows Private-network firewall rule for TCP
50415. Xbox telemetry uses UDP 20440. The README contains the exact commands.
