# Receipt Composer Shortcode Reference

Every server-to-printer mapping has its own single, unified design, written as
one line of text mixing literal characters with shortcode tags like
`[align:center]`. There's no separate header/footer to think about — a
`[body]` tag marks where the incoming print job's own content goes, and
everything else in the template is decoration around it. If the same
physical printer is mapped from several endpoints (a kitchen ticket, a
register receipt, a delivery slip), each mapping gets its own independent
design and print counters — editing one never affects another.
The Receipt Composer settings window builds this same text for you through
its block editor, but you can also type or paste it directly — see the
Blocks/Plain Text toggle at the top of each editor. This file and the
in-app "Shortcode Reference" panel (top of the Receipt Composer window)
describe the same syntax; the in-app version is always the authoritative one
for the version you're running.

A tag looks like `[name]` or `[name:argument]`. `[bold]` is a paired tag:
everything between `[bold]` and `[/bold]` is bold.

**Unknown or misspelled tags never print as literal text.** `[algn:center]`
(typo) or `[blorp]` (made up) silently produce nothing, rather than printing
the literal characters on an unattended receipt. The one exception is
`[counter:some_new_name]` — a counter name that doesn't exist yet is created
automatically rather than dropped, since the tag itself is still valid, only
the name is new.

## Text & layout

| Shortcode | What it does |
| --- | --- |
| `[body]` | Marks where the incoming print job's own content goes. If you never add it, the content is still appended automatically at the end, so it's never silently dropped — only the first use counts, a second `[body]` is ignored rather than printing the content twice. |
| `[align:left]` / `[align:center]` / `[align:right]` | Sets alignment for everything printed after it, until changed again. |
| `[bold]...[/bold]` | Bolds the text between the two tags. |
| `[hr]` | A dashed line the width of the printer's configured Characters per Line. |
| `[blank]` | One blank line. Add this tag again for each extra line, or use `[feed:N]` below to add several at once — they produce the same result, `[feed:N]` is just more compact. |
| `[newline]` | A line break — the same one line of blank space as `[blank]`, just a different name for the same tag. |

## Dynamic content

| Shortcode | What it does |
| --- | --- |
| `[date]` | Today's date, formatted `YYYY-MM-DD`. |
| `[date:FORMAT]` | Date and/or time in a custom format, using Python's [`strftime`](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes) codes — `%Y` `%m` `%d` `%H` `%M` `%S` `%p` and so on. The Date block in the settings window has a dropdown of common presets (date only, various date/time combinations, 12h/24h time) that fill in a starting format, which you can then edit freely. |
| `[random]` / `[random:N]` | A random number, 6 digits by default, or `N` digits (1-12), zero-padded. |
| `[print_number]` | The mapping's built-in running counter — every mapping has one automatically, no setup required, independent of any other mapping even on the same physical printer. Increases by 1 on every real print (Test Print included); previewing a template never increments it. |
| `[counter:name]` | A counter you name yourself, tracked independently of the default one — useful for separate sequences, e.g. one counter for dine-in receipts and another for takeout. Add, reset, or remove named counters in the Print Counters section of the Receipt Composer window. |

## Images

| Shortcode | What it does |
| --- | --- |
| `[image:id]` | Prints an uploaded image as a monochrome ESC/POS raster bitmap (`GS v 0`), dithered by default. Upload the image first under Uploaded Images in the Receipt Composer window, then pick it from an Image block — the `id` is assigned automatically, you never type it by hand. |

## Printer commands

| Shortcode | What it does |
| --- | --- |
| `[cut:full]` / `[cut:partial]` | Cuts the paper. |
| `[cut:full:N]` / `[cut:partial:N]` | Feeds `N` lines immediately before cutting, then cuts. Most thermal printers mount the cutter blade some distance below the print head, so cutting right after the last line can slice through content that hasn't cleared the blade yet — if your receipts keep getting cut through the middle of the text, add a Cut block (or edit an existing one) and increase its "Feed lines before cutting" field until the cut lands cleanly past the content. Omitting `:N` (or setting it to 0) behaves exactly like plain `[cut:full]` — no extra feed. |
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
[body]
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

## Migrating from per-printer designs

Earlier Pridge Client versions kept one shared header/footer design per local
printer, so several server mappings pointing at the same physical printer all
showed (and edited) the exact same content. The first time a config from that
era loads, every mapping that shared a printer's old design gets its own
identical copy of it — the same content the printer used to show — and from
then on each mapping's design is edited and printed independently. Nothing
needs to be done by hand.

## Migrating from separate header/footer templates

A brief earlier version of Receipt Composer had a separate header and footer
per mapping, with the print job's real content implicitly sandwiched between
them. The first time a mapping from that version loads, its header and footer
are combined into a single template automatically, with a `[body]` tag
inserted between them — `header + [body] + footer` — so it behaves exactly
like it always did. Nothing needs to be done by hand.
