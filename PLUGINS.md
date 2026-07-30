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

## Receipt Composer shortcodes (optional, any plugin)

Any renderer plugin — built-in or third-party — can contribute its own
`[tag]` shortcodes to Receipt Composer's RAW header/footer templates. This is
a plain Python attribute on the plugin object (not a manifest field), read
generically via `getattr` so a plugin never has to declare it:

```python
class MyPlugin:
    ...
    def __init__(self):
        self.receipt_shortcodes = {
            "weather": self._resolve_weather,
        }

    def _resolve_weather(self, arg):
        # arg is the tag's raw argument as a string, or None if the tag had
        # no `:argument` (e.g. "[weather]" vs "[weather:sunny]").
        return f"Weather: {arg or 'unknown'}".encode("ascii")
```

`receipt_shortcodes` is a `dict[str, Callable[[str | None], bytes]]`: each key
is the tag name (matched case-insensitively, e.g. `"weather"` handles both
`[weather]` and `[WEATHER:sunny]`), and each value is a function taking the
tag's argument and returning the literal bytes to splice into the printed
output. Your resolver is only ever consulted after every built-in tag name
(`align`, `bold`, `hr`, `blank`, `newline`, `date`, `random`, `print_number`,
`counter`, `image`, `cut`, `drawer`, `feed`, `hex`, `dec`) has been ruled
out — a plugin can never shadow or override the built-in vocabulary, and an
attempt to do so is ignored with a logged warning. If two enabled plugins
register the same custom name, the one with higher priority (lower priority
number, same ordering as the Plugins window's drag-to-reorder) wins; the
other is ignored with a logged warning — reorder plugin priority to change
which one applies.

Your resolver must never raise: if it does, or returns anything other than
`bytes`/`bytearray`, the tag resolves to nothing (same "never print garbage
on an unattended receipt" rule the built-in tags follow) rather than
crashing the print job or the settings-window preview. In the live block
editor preview, a custom tag always renders as an opaque marker showing its
tag name — Pridge Client has no way to know whether your resolver's output is
printable text or a raw ESC/POS sequence, so it doesn't attempt to decode it.

Scope note: only simple, self-closing tags (`[name]` / `[name:arg]`) can be
contributed this way. Paired open/close tags like `[bold]...[/bold]` are not
currently an extension point — closing tags are matched only against the
small built-in set (`bold`) and are not routed to `receipt_shortcodes` at all.

## Settings window (core plugins only)

A plugin object can carry an optional `settings_window: str` attribute (a
plain Python class/instance attribute, not a manifest field). When present
and non-empty, the Plugins window shows a **Settings** button on that
plugin's row; clicking it calls `open_plugin_settings_window(settings_window)`
in `gui.py`, which dispatches through a small `openers` dict to the matching
`_open_utility_window(...)` call (see `open_app_mapping_window` and
`open_receipt_composer_window`).

This attribute exists so Pridge Client's own built-in plugins (App Mapping,
Receipt Composer) don't each need bespoke, hardcoded wiring in the Plugins
window — `has_settings`/`settings_window` are read generically via
`getattr`. It is **not** yet a general extension point for third-party
manifest-based plugins: the `openers` dict only recognizes the window keys
Pridge Client ships with, so setting an arbitrary `settings_window` value on
a third-party plugin will show a Settings button that errors when clicked.
Registering a plugin-supplied settings window is a possible future addition,
not something available today.

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
