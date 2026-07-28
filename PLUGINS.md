# Writing a Pridge Client Plugin

Pridge Client's plugin system is not limited to printing: the manifest format
and install mechanism are generic. Every plugin installed today still uses
the renderer contract described below (it converts a document into PDF for
System Driver printing), but `category` is a free-form label you choose
yourself, purely for how the Plugins window groups and displays plugins — it
is not a fixed enum. Pridge Client's own built-in plugins use `"Renderer"`
(the PDF/Image/Text/SVG plugins) and `"Mapper"` (the External Application
Mapper), but a third-party plugin can declare any category name, e.g.
`"BingiBongo"`, and it will get its own tab in the Plugins window.

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
| `category` | yes | Any non-empty label you choose. Controls which tab your plugin appears under in the Plugins window; it does not affect how the plugin is loaded or used. |
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

## Dashboard widgets (optional, any plugin)

Any renderer plugin can also contribute a widget to the dashboard's widget
area — this is not a separate category, just two extra manifest fields:

```json
{
  "widget_title": "My Widget",
  "widget_entry": "widget.js"
}
```

Both must be set for the widget to appear in the **Add Widget** picker;
`widget_entry` is a plain JavaScript file next to `manifest.json`. When a
user adds your widget, Pridge Client reads that file's source and injects it
as an inline `<script>` directly into the dashboard page. Your script runs
once, synchronously, and must mount into the container Pridge Client already
created for it:

```javascript
(function () {
  var container = document.getElementById(window.PridgeWidgetContainerId);
  container.innerHTML = "<strong>Hello from my widget</strong>";
})();
```

`window.PridgeWidgetContainerId` is set immediately before your script runs
and only describes your own widget's container — read it right away rather
than caching it, since the next widget added overwrites it for its own
script. A complete example lives at
[`tests/fixtures/example_widget_plugin/`](tests/fixtures/example_widget_plugin/).

Widget scripts are **not sandboxed**: your code runs with full access to the
live dashboard page (its DOM, its `pywebview.api` bridge, everything else on
the page), exactly like Pridge's own UI code. Only install widget plugins
you trust as much as you'd trust any other code running in the application.

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
