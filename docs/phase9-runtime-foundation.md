# Phase 9: recording and desktop runtime foundation

This phase makes the service safe to package as a background desktop app. Live
UDP processing stays in memory, while a separate recorder thread samples the
latest valid packet into SQLite at 5 Hz by default.

## Permanent files

The default Windows folder is `%LOCALAPPDATA%\FH6 Telemetry`. macOS uses
`~/Library/Application Support/FH6 Telemetry`, and Linux uses
`$XDG_DATA_HOME/fh6-telemetry` (or `~/.local/share/fh6-telemetry`). Set
`FH6_HOME` to override the entire folder.

The folder contains:

- `config.json` — persistent, human-editable settings
- `data/telemetry.sqlite3` — sessions and sampled telemetry
- `logs/fh6-telemetry.log` — current log, plus up to five rotated backups
- `exports/` — reserved for exports saved by the desktop shell
- `fh6-telemetry.lock` — process ownership marker; a leftover file is harmless

## Session behavior

A session begins with the first valid connected packet. It ends after ten
seconds without valid telemetry, when the car changes, or when the service
shuts down. Shutdown writes the final timestamp and reason before SQLite is
closed. At 5 Hz, one hour produces at most 18,000 sample rows instead of storing
every native UDP packet.

Session endpoints are:

- `GET /api/recording`
- `GET /api/sessions?limit=100`
- `GET /api/sessions/{id}`
- `GET /api/sessions/{id}/export.csv`
- `GET /api/sessions/{id}/export.json`

Both export formats stream from the database and therefore remain safe for
long drives.

## Configuration precedence

Environment variables override `config.json`, and the file overrides built-in
defaults. Existing variables remain supported. New variables are:

- `FH6_RECORDING_ENABLED`
- `FH6_RECORDING_HZ`
- `FH6_SESSION_END_TIMEOUT`
- `FH6_LOG_MAX_BYTES`
- `FH6_LOG_BACKUP_COUNT`
- `FH6_HOME`

Only one service can own a given data folder at a time. The operating system
releases the lock automatically after a crash, so no manual lock-file cleanup
is required.
