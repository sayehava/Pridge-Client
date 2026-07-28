# Receipt Composer Shortcode Reference

Every RAW-mode printer has a header and a footer, each written as a single line
of text mixing literal characters with shortcode tags like `[align:center]`.
The Receipt Composer settings window builds this same text for you through
its block editor, but you can also type or paste it directly — see the
Blocks/Plain Text toggle at the top of each editor. This file and the
in-app "Shortcode Reference" panel (top of the Receipt Composer window)
describe the same syntax; the in-app version is always the authoritative one
for the version you're running.

A tag looks like `[name]` or `[name:argument]`. Two tags — `[bold]` and
`[italic]` — are paired: everything between `[bold]` and `[/bold]` is bold.

**Unknown or misspelled tags never print as literal text.** `[algn:center]`
(typo) or `[blorp]` (made up) silently produce nothing, rather than printing
the literal characters on an unattended receipt. The one exception is
`[counter:some_new_name]` — a counter name that doesn't exist yet is created
automatically rather than dropped, since the tag itself is still valid, only
the name is new.

## Text & layout

| Shortcode | What it does |
| --- | --- |
| `[align:left]` / `[align:center]` / `[align:right]` | Sets alignment for everything printed after it, until changed again. |
| `[bold]...[/bold]` | Bolds the text between the two tags. |
| `[italic]...[/italic]` | Shown in the block editor's preview only. There is no universal ESC/POS italic command, so on real hardware this prints as normal text — a documented no-op, not a bug. |
| `[hr]` | A dashed line the width of the printer's configured Characters per Line. |
| `[blank]` | A blank line. |
| `[newline]` | A line break. |

## Dynamic content

| Shortcode | What it does |
| --- | --- |
| `[date]` | Today's date, formatted `YYYY-MM-DD`. |
| `[date:FORMAT]` | Date and/or time in a custom format, using Python's [`strftime`](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes) codes — `%Y` `%m` `%d` `%H` `%M` `%S` `%p` and so on. The Date block in the settings window has a dropdown of common presets (date only, various date/time combinations, 12h/24h time) that fill in a starting format, which you can then edit freely. |
| `[random]` / `[random:N]` | A random number, 6 digits by default, or `N` digits (1-12), zero-padded. |
| `[print_number]` | The printer's built-in running counter — every printer has one automatically, no setup required. Increases by 1 on every real print (Test Print included); previewing a template never increments it. |
| `[counter:name]` | A counter you name yourself, tracked independently of the default one — useful for separate sequences, e.g. one counter for dine-in receipts and another for takeout. Add, reset, or remove named counters in the Print Counters section of the Receipt Composer window. |

## Images

| Shortcode | What it does |
| --- | --- |
| `[image:id]` | Prints an uploaded image as a monochrome ESC/POS raster bitmap (`GS v 0`), dithered by default. Upload the image first under Uploaded Images in the Receipt Composer window, then pick it from an Image block — the `id` is assigned automatically, you never type it by hand. |

## Printer commands

| Shortcode | What it does |
| --- | --- |
| `[cut:full]` / `[cut:partial]` | Cuts the paper. |
| `[drawer]` | Opens the cash drawer, on printers wired for it. |
| `[feed]` / `[feed:N]` | Feeds `N` blank lines, 4 by default. |
| `[hex:1D 56 00]` | Sends raw bytes given in hexadecimal — an escape hatch for any command not covered by the shortcodes above. Spaces, colons, and dashes are all accepted as separators. Malformed hex resolves to nothing rather than raising an error. |
| `[dec:29 86 0]` | The same escape hatch as `[hex:...]`, but with byte values given in decimal instead — handy when a printer's command reference lists decimal values rather than hex. Space- or comma-separated, each value 0-255; any invalid or out-of-range value resolves the whole tag to nothing. |

## Example

```text
[align:center][bold]ACME COFFEE[/bold][/align:left]
[image:5f3a...]
[hr]
[align:left]Order #[print_number]
[date:%Y-%m-%d %H:%M]
[hr]
[align:center]Thank you for your visit![newline][newline]
[cut:full]
```

## Migrating from the old preset dropdowns

Earlier Pridge Client versions had a simpler RAW header/footer made of five
fixed presets (Full Cut, Partial Cut, Open Cash Drawer, Feed, Custom hex) with
no block editor. Any printer profile still holding one of those presets is
migrated automatically the first time it loads — `full_cut` becomes
`[cut:full]`, `partial_cut` becomes `[cut:partial]`, `open_drawer` becomes
`[drawer]`, `feed` becomes `[feed:4]`, and a custom hex value becomes
`[hex:...]`. Nothing needs to be done by hand; the presets themselves are no
longer editable from the UI once migrated.
