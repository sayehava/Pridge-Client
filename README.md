# PrintBridge Endpoint Agent

PrintBridge Endpoint Agent is the local desktop application that connects an office computer to PrintBridge Server, receives print jobs, and sends raw payloads to local printers.

This repository contains the first Python implementation. The server protocol is intentionally simple and language-neutral so future agents written in C++, Rust, C#, Go, or another language can reuse the same API.

## Installation

Use Python 3.9 or newer.

```bash
python3 -m pip install -e .
```

Optional platform packages:

- Windows RAW printing: `python3 -m pip install -e ".[windows]"`
- Linux CUPS integration: `python3 -m pip install -e ".[linux]"`
- Secure token storage: `python3 -m pip install -e ".[secure]"`

The application can run without the optional secure storage package. If `keyring` is unavailable, the client token is stored in a restricted local fallback file.

## Running

Open the settings window:

```bash
python3 -m printbridge_endpoint
```

Run in background/headless mode:

```bash
python3 -m printbridge_endpoint --headless
```

Show the installed version:

```bash
python3 -m printbridge_endpoint --version
```

When running from a source checkout without installing, set `PYTHONPATH=src`.

## Connect to Servers

Use the settings window to connect the endpoint to one or more PrintBridge Server instances:

1. Enter a server name, server URL, and client token.
2. Leave `Enabled` checked if this server should poll for jobs.
3. Set the polling and heartbeat intervals, or let the server override them in heartbeat/reserve responses.
4. Click `Add Server`.
5. Repeat for every server this office computer should serve.
6. Select the local printer under `Global Settings`.
7. Click `Start`.

The endpoint starts one background polling worker for each enabled server profile. All enabled servers can send jobs to the same selected local printer unless a reserved job response includes a specific `printer_name`.

Stored tokens are hidden. To replace a token, select the server profile, enter the new token, and click `Update Server`.

## Configuration

The settings window stores:

- server profiles
- selected printer
- polling interval per server
- heartbeat interval per server
- start polling on launch
- start at login
- logging preferences

Client tokens are stored separately per server through the operating system credential store when `keyring` is available. Stored tokens are not shown in the GUI. Enter a token only when setting or replacing it.

Configuration locations:

- Windows: `%APPDATA%\PrintBridge Endpoint\config.json`
- macOS: `~/Library/Application Support/PrintBridge Endpoint/config.json`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/printbridge-endpoint/config.json`

## Authentication

The endpoint authenticates with the client token issued by PrintBridge Server. A successful authentication response must include:

```json
{
  "session_token": "temporary-session-token"
}
```

Future requests use:

```http
Authorization: Bearer SESSION_TOKEN
```

If a request returns HTTP 401, the endpoint clears the session token, authenticates again, and retries the request once.

## Server API

The current endpoint client expects these language-neutral JSON endpoints:

- `POST /api/endpoint/auth`
- `POST /api/endpoint/heartbeat`
- `POST /api/endpoint/jobs/reserve`
- `POST /api/endpoint/jobs/{job_id}/status`

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

The server remains responsible for requeueing jobs that were reserved but never completed because the endpoint crashed or disconnected.

## Printer Selection

Printer discovery is platform-specific behind a shared interface:

- Windows: `pywin32`
- Linux: `pycups` when installed, otherwise `lpstat`
- macOS: `lpstat`

Printing sends raw bytes to the selected printer:

- Windows: `StartDocPrinter` with `RAW`
- Linux/macOS: `lp -o raw`

The endpoint does not interpret or transform print payloads. Base64 is decoded to bytes and sent as received.

## Background Operation

The worker processes one job at a time:

1. authenticate if needed
2. send heartbeat when due
3. reserve one job
4. report `printing`
5. print raw bytes
6. report `printed` or `failed`

Temporary network, server, authentication, and printer errors are retried with bounded backoff.

## Auto-Start

The settings window can enable login startup:

- Windows: current-user Run key
- macOS: `~/Library/LaunchAgents/com.printbridge.endpoint.plist`
- Linux: XDG autostart desktop entry

Auto-start launches the endpoint in `--headless` mode.

## Logging

Logs include startup, authentication, heartbeat, printer changes, job lifecycle events, and safe error messages. Logs redact token-like values and never include raw print payloads.

Log locations:

- Windows: `%LOCALAPPDATA%\PrintBridge Endpoint\Logs\endpoint.log`
- macOS: `~/Library/Logs/PrintBridge Endpoint/endpoint.log`
- Linux: `${XDG_STATE_HOME:-~/.local/state}/printbridge-endpoint/endpoint.log`

## Troubleshooting

If no printers appear, verify that the operating system can list printers with its native tools (`lpstat -p` on macOS/Linux, Windows printer settings on Windows).

If jobs fail immediately, verify that:

- the server URL is reachable
- the client token is valid
- the selected printer exists
- the print server accepts raw payloads for that printer
- optional platform packages are installed where required

If authentication keeps failing, replace the token in the settings window. Stored tokens are hidden and cannot be inspected from the GUI.

## Packaging

The project exposes the `printbridge-endpoint` console script through `pyproject.toml`. A packaged desktop build can wrap this entry point and launch the GUI by default or `--headless` for background operation.

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
