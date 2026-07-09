# PrintBridge Endpoint Agent

PrintBridge Endpoint Agent is the local desktop application that connects an office computer to PrintBridge Server, receives print jobs, and sends raw payloads to local printers.

This repository contains the first Python implementation. The runtime protocol is kept language-neutral so future endpoint agents can reuse the same server API.

## Development

Run the application from the repository root:

```bash
python -m printbridge_endpoint
```

Run syntax validation:

```bash
python -m compileall src
```
