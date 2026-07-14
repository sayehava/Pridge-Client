# Pridge Client

Pridge Client is the local desktop application that connects an office computer to PrintBridge Server, receives print jobs, and sends them to local printers as unchanged RAW data or through an installed system printer driver.

This repository contains the first Python implementation. The server protocol is intentionally simple and language-neutral so future clients written in C++, Rust, C#, Go, or another language can reuse the same API.

Self-contained Native (Nuitka) and PyInstaller release builds for Windows and macOS are documented in [BUILDING.md](BUILDING.md).

## Installation

Use Python 3.9 or newer.

```bash
python3 -m pip install -e .
```

Optional platform packages:

- Windows printing: `python3 -m pip install -e ".[windows]"`
- Linux CUPS integration: `python3 -m pip install -e ".[linux]"`
- Secure token storage: `python3 -m pip install -e ".[secure]"`

The application can run without the optional secure storage package. If `keyring` is unavailable, the client token is stored in a restricted local fallback file.

## Running

Open the settings window:

```bash
python3 -m printbridge_client
```

Run in background/headless mode:

```bash
python3 -m printbridge_client --headless
```

Show the installed version:

```bash
python3 -m printbridge_client --version
```

When running from a source checkout without installing, set `PYTHONPATH=src`.

## Connect to Servers

Use the settings window to connect the client to one or more PrintBridge Server instances:

1. Click `Add Server` in the `Server Connections` list.
2. Enter a server name, server URL, and client token in the separate server settings window.
3. Leave `Enabled` checked if this server should poll for jobs.
4. Set that server's polling and heartbeat intervals.
5. Click `Test Connection` to verify the URL and token.
6. Under `Remote Printer Mappings`, wait for all server endpoints and installed local printers to load automatically.
7. Use each endpoint's dropdown to select a local printer. Leave `Disabled` selected when that endpoint should not be assigned to this client.
8. Click `Configure` next to a selected local printer and choose `RAW data` or `System driver`.
9. For System Driver mode, select the options reported by CUPS/macOS or open the installed driver's native preferences on Windows, then save the printer settings.
10. Click `Add Server` to save the connection.
11. Repeat for every server this office computer should serve.
12. Use the Start and Stop buttons on each server card to control servers independently.

The client starts one background polling worker for each enabled server profile. Printer mappings are independent per server, so different remote queues can target different local printers while still sharing the same client application.

The main window lists every configured server with its enabled state, token state, polling interval, heartbeat interval, printer-mapping count, and current worker status. Each server has independent Start and Stop controls. Click `Edit` to open that server in a separate settings window. Stored tokens are hidden; enter a new token only when replacing the existing token.

Server cards are shown one at a time in an animated carousel, so large installations remain responsive without stacking cards. A newly added server becomes the active slide automatically. The server editor keeps its main form fixed and scrolls only a compact remote-printer mapping panel.

## Configuration

The settings window stores:

- server profiles
- remote-to-local printer mappings per server
- printing mode and driver settings per installed local printer
- polling interval per server
- heartbeat interval per server
- start polling on launch
- start at login
- window darkness grade
- logging preferences

Client tokens are stored separately per server through the operating system credential store when `keyring` is available. Stored tokens are not shown in the GUI. Enter a token only when setting or replacing it.

Configuration locations:

- Windows: `%APPDATA%\Pridge Client\config.json`
- macOS: `~/Library/Application Support/Pridge Client/config.json`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/pridge-client/config.json`

When the new configuration does not exist, the client copies existing PrintBridge Client or Endpoint-era configuration and credentials into the Pridge locations. The legacy files and keyring entries are not deleted.

## Authentication

The client authenticates with the client token issued by PrintBridge Server. A successful authentication response must include:

```http
POST /api/client/auth
Content-Type: application/json
```

```json
{
  "token": "client-token"
}
```

The server returns:

```json
{
  "token": "temporary-session-token"
}
```

Future requests use:

```http
Authorization: Bearer SESSION_TOKEN
```

If a request returns HTTP 401, the client clears the session token, authenticates again, and retries the request once.

## Server API

The current client expects these language-neutral JSON endpoints:

- `POST /api/client/auth`
- `GET /api/client/endpoints`
- `PUT /api/client/endpoints`
- `GET /api/client/jobs`
- `POST /api/client/heartbeat`
- `POST /api/client/jobs/reserve`
- `POST /api/client/jobs/{job_id}/printing`
- `POST /api/client/jobs/{job_id}/printed`
- `POST /api/client/jobs/{job_id}/failed`

Job reservation can return HTTP 204 when no job is available, or JSON:

```json
{
  "job": {
    "id": "job-id",
    "payload_base64": "base64-encoded-raw-bytes",
    "content_type": "application/octet-stream",
    "printer_name": "optional-printer-name",
    "copies": 1
  }
}
```

Supported reported states are:

- `printing`
- `printed`
- `failed`

The server remains responsible for requeueing jobs that were reserved but never completed because the client crashed or disconnected.

## Printer Mapping

Printer discovery is platform-specific behind a shared interface:

- Windows: `pywin32`
- Linux: `pycups` when installed, otherwise `lpstat`
- macOS: `lpstat`

Each server profile maps remote PrintBridge endpoint IDs to local printer names. The client reads `endpoint_id` from a reserved job and routes the payload through that server's mapping. A server endpoint whose selector is `Disabled` has no local mapping, so its job is reported as failed instead of being sent to an arbitrary printer.

The settings window loads all virtual printer endpoints from `GET /api/client/endpoints`. It also refreshes the operating system's local printer list whenever the server editor opens. Saving a server sends every non-disabled endpoint ID to `PUT /api/client/endpoints`, making the local printer dropdown the source of that client's server assignments. Older servers without the endpoint-list route fall back to discovering endpoints from their active job list.

## Printing Modes

Printing mode and page/job settings are stored once per installed local printer, so mappings from multiple servers share the same printer profile. Existing configurations default to `raw`.

`raw` mode sends the decoded payload bytes directly to the resolved printer:

- Windows: `StartDocPrinter` with `RAW`
- Linux/macOS: `lp -o raw`

The client does not interpret or transform RAW payloads. Base64 is decoded to bytes and sent as received, including null bytes, line endings, and printer-control commands. Generic page setup is intentionally unavailable in RAW mode.

`system_driver` mode submits the document through the operating system printing path:

- Windows: the registered `PrintTo` document handler and the installed printer driver; `Open Driver Settings` displays the driver's native preferences window, which owns and saves its supported options
- Linux/macOS: CUPS `lp`; `lpoptions` supplies the exact option IDs, choices, display labels, and defaults shown in Pridge Client

CUPS options can include media or label size, orientation, resolution, input source, media type, duplex, cutter behavior, and other driver-specific controls. Only options reported by the current driver are shown. Saved values are validated again before each system-driver job; removed or changed choices fall back to the driver's current default.

System-driver payloads should include an accurate `content_type`, such as `application/pdf` or `image/png`. On Windows, the document type must also have an installed application that supports the operating system's `PrintTo` action. Rendering and conversion remain the responsibility of that application, the operating system, and the printer driver.

## Background Operation

The worker processes one job at a time:

1. authenticate if needed
2. send heartbeat when due
3. reserve one job
4. report `printing`
5. print through the local printer's saved RAW or system-driver profile
6. report `printed` or `failed`

Temporary network, server, authentication, and printer errors are retried with bounded backoff.

Each server runs in its own worker and has independent polling and heartbeat intervals. Editing a running server restarts only that server so URL, token, timing, and printer-mapping changes take effect immediately.

## Desktop Interface

The GUI uses a bundled pywebview interface with glossy layered panels over an opaque native window on every platform. Appearance settings offer six named stone palettes—Quartz, Moonstone, Labradorite, Onyx, Obsidian, and Jet. Each palette changes the full workspace color system, including its base, ambient glows, sidebar, cards, controls, borders, and accent color.

Confirmations use branded in-app dialogs with the Pridge application icon instead of browser or Python-native message boxes.

## Auto-Start

The settings window can enable login startup:

- Windows: current-user Run key
- macOS: `~/Library/LaunchAgents/com.pridge.client.plist`
- Linux: XDG autostart desktop entry

Auto-start launches the client in `--headless` mode.

## Logging

Logs include startup, authentication, heartbeat, printer changes, job lifecycle events, and safe error messages. Logs redact token-like values and never include raw print payloads.

Log locations:

- Windows: `%LOCALAPPDATA%\Pridge Client\Logs\client.log`
- macOS: `~/Library/Logs/Pridge Client/client.log`
- Linux: `${XDG_STATE_HOME:-~/.local/state}/pridge-client/client.log`

## Troubleshooting

If no printers appear, verify that the operating system can list printers with its native tools (`lpstat -p` on macOS/Linux, Windows printer settings on Windows).

If jobs fail immediately, verify that:

- the server URL is reachable
- the client token is valid
- every enabled remote endpoint is mapped to an installed local printer
- RAW jobs contain printer-ready bytes supported by that printer
- system-driver jobs have the correct content type and an installed document handler
- the selected driver option still exists in the operating system's current printer configuration
- optional platform packages are installed where required

If authentication keeps failing, replace the token in the settings window. Stored tokens are hidden and cannot be inspected from the GUI.

## Packaging

The project exposes `pridge-client` as its console script. A packaged desktop build can launch the GUI by default or use `--headless` for background operation.

## License

Pridge Client is free software licensed under GNU General Public License version 3 or, at your option, any later version (`GPL-3.0-or-later`). See [LICENSE](LICENSE) for the full license text.

The project also carries an attribution requirement permitted by GNU GPLv3 Section 7(b). Modified or redistributed versions with an interactive user interface must keep this notice visible in their About or Legal Notices section:

> Original author: Sayeh Ava Pazouki<br>
> Copyright © 2026 Sayeh Ava Pazouki

See [ADDITIONAL_TERMS.md](ADDITIONAL_TERMS.md) for the complete additional term.

## Updating

After pulling updates, reinstall editable dependencies if metadata changed:

```bash
python3 -m pip install -e .
```

Then validate the source:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPYCACHEPREFIX=/tmp/printbridge_pycache python3 -m compileall src tests
```
---

### ❤️ Support Development

☕ **Buy Me a Coffee**  
https://buymeacoffee.com/sayehava

💜 **Ko-fi**  
https://ko-fi.com/sayehava

> [!TIP]
> Even a small donation helps fund future modules, maintenance, bug fixes, and new features.

---
