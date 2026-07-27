# Writing a Pridge Client Plugin

Pridge Client's plugin system is not limited to printing: the manifest format
and install mechanism are generic, and "renderer" (a plugin that converts a
document into PDF for System Driver printing) is the first supported plugin
category. This document covers renderer plugins, the only category shipped
today.

## How discovery works

At startup, and whenever you click **Rescan Plugins**, Pridge Client scans:

- Windows: `%APPDATA%\Pridge Client\plugins\renderers\`
- macOS: `~/Library/Application Support/Pridge Client/plugins/renderers/`
- Linux: `${XDG_CONFIG_HOME:-~/.config}/pridge-client/plugins/renderers/`

Each subfolder containing a `manifest.json` is treated as one plugin. A
plugin that fails to load (bad manifest, unsupported API version, missing
entry point) is shown with its error in the Plugins window instead of
crashing the client — one broken plugin never blocks the others or the
startup.

## Installing a plugin

Use the **Plugins** button in the sidebar (above Settings and About), then
**Install Plugin** and select the plugin's folder. Pridge Client validates
`manifest.json` and copies the folder into the plugins directory above. Use
**Remove** on a third-party plugin's row to uninstall it; built-in plugins
have no Remove button.

## Plugin folder layout

```text
my-plugin/
  manifest.json
  plugin.py
```

## manifest.json

```json
{
  "id": "org.example.pridge.renderer.example",
  "name": "Example Renderer",
  "version": "1.0.0",
  "api_version": 1,
  "category": "renderer",
  "entry_point": "plugin:ExampleRendererPlugin",
  "supported_mime_types": ["application/x-pridge-example"],
  "supported_extensions": [".example"]
}
```

| Field | Required | Notes |
| --- | --- | --- |
| `id` | yes | Globally unique. Recommended form: `reverse.domain.pridge.renderer.name`. |
| `name` | yes | Display name shown in the Plugins window. |
| `version` | no | Your plugin's own version string. Defaults to `0.0.0`. |
| `api_version` | yes | Must equal the renderer API version Pridge Client supports (currently `1`). A mismatch is rejected with a clear error, not a crash. |
| `category` | yes | Only `"renderer"` is supported today. |
| `entry_point` | yes | `module:ClassName`, where `module.py` sits next to `manifest.json`. |
| `supported_mime_types` | no | Used during renderer selection. |
| `supported_extensions` | no | Used during renderer selection. |

## The renderer contract

A renderer plugin does not need to import anything from `pridge_client`. The
contract is structural (a `Protocol`, see
`src/pridge_client/renderers/base.py`): any object exposing these attributes
and methods is accepted.

```python
class ExampleRendererPlugin:
    plugin_id = "org.example.pridge.renderer.example"
    display_name = "Example Renderer"
    version = "1.0.0"
    api_version = 1
    supported_mime_types = frozenset({"application/x-pridge-example"})
    supported_extensions = frozenset({".example"})

    def can_render(self, *, mime_type, filename, data):
        # Optional fallback: return True if this plugin can handle
        # `data` even without a MIME/extension match.
        return False

    def render_to_pdf(self, *, data, mime_type, filename, options):
        # Must return a valid PDF document as bytes, or raise
        # RenderError("...") with a clear message. Never print directly.
        ...
```

A complete, runnable example lives at
[`tests/fixtures/example_renderer_plugin/`](tests/fixtures/example_renderer_plugin/).
Copy that folder as a starting point.

## Renderer selection order

When a system-driver job needs a renderer, Pridge Client picks one in this
order: an explicitly requested plugin ID, then an exact MIME type match,
then an exact file extension match, then magic-byte content detection, then
each enabled plugin's own `can_render()`. The Plugins window lets you
reorder plugin priority and enable/disable individual plugins, including
built-ins.

## Security

Third-party plugins execute arbitrary Python code with Pridge Client's own
privileges. Only install plugins you trust. Pridge Client validates the
manifest and rejects duplicate IDs and incompatible API versions before
loading any code, and isolates a plugin's load/render failures so they
never crash the application, but it does not sandbox plugin execution.

## RAW printing is unaffected

Renderer plugins only apply to **System Driver** mode. RAW jobs (ESC/POS,
ZPL, PCL, printer-specific PostScript, and similar) are sent to the printer
unchanged and never pass through the renderer pipeline.
