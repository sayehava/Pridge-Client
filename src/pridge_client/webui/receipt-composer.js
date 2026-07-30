/*
 * SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.
 */

(() => {
  "use strict";

  const { useEffect, useRef, useState } = React;
  const html = htm.bind(React.createElement);
  const S = window.PridgeStrings;

  function callApi(name, ...args) {
    if (!window.pywebview || !window.pywebview.api || !window.pywebview.api[name]) return Promise.resolve(null);
    return window.pywebview.api[name](...args);
  }

  function whenApiReady(callback, attempts = 0) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_state) {
      callback();
      return;
    }
    if (attempts < 200) window.setTimeout(() => whenApiReady(callback, attempts + 1), 50);
  }

  function uid() {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  // ------------------------------------------------------------------
  // Template <-> block conversion. This mirrors the tokenizer in
  // pridge_client/receipt_composer/shortcodes.py (TAG_RE) so any template
  // saved from elsewhere (including migrated legacy presets) round-trips
  // through this editor without silently losing content: unrecognized tags
  // become a read-only "raw" block instead of being dropped.
  // ------------------------------------------------------------------
  const TAG_RE = /\[(\/?)([a-zA-Z_]+)(?::([^\]]*))?\]/g;

  function tagToBlock(closing, name, arg, full) {
    if (closing) {
      if (name === "bold") return { kind: "bold_toggle", state: "off" };
      return { kind: "raw", value: full };
    }
    switch (name) {
      case "align":
        return { kind: "align", value: (arg || "left").trim().toLowerCase() || "left" };
      case "bold":
        return { kind: "bold_toggle", state: "on" };
      case "hr":
        return { kind: "hr" };
      case "blank":
        return { kind: "blank" };
      case "newline":
        return { kind: "newline" };
      case "date":
        return { kind: "date", format: arg || "" };
      case "random":
        return { kind: "random", digits: arg ? parseInt(arg, 10) || 6 : 6 };
      case "print_number":
        return { kind: "print_number" };
      case "counter":
        return { kind: "counter", key: arg || "" };
      case "image":
        return { kind: "image", imageId: arg || "" };
      case "cut": {
        const parts = (arg || "").split(":");
        const feedBefore = parts.length > 1 ? Math.max(0, parseInt(parts[1], 10) || 0) : 0;
        return { kind: "cut", value: (parts[0] || "full").trim().toLowerCase() || "full", feedBefore };
      }
      case "drawer":
        return { kind: "drawer" };
      case "feed":
        return { kind: "feed", lines: arg ? parseInt(arg, 10) || 4 : 4 };
      case "hex":
        return { kind: "hex", value: arg || "" };
      case "dec":
        return { kind: "dec", value: arg || "" };
      case "body":
        return { kind: "body" };
      default:
        return { kind: "raw", value: full };
    }
  }

  function parseTemplate(template) {
    const blocks = [];
    let lastIndex = 0;
    let match;
    TAG_RE.lastIndex = 0;
    while ((match = TAG_RE.exec(template || "")) !== null) {
      const literal = template.slice(lastIndex, match.index);
      if (literal) blocks.push({ kind: "text", value: literal });
      lastIndex = TAG_RE.lastIndex;
      blocks.push(tagToBlock(match[1] === "/", match[2].toLowerCase(), match[3], match[0]));
    }
    const trailing = (template || "").slice(lastIndex);
    if (trailing) blocks.push({ kind: "text", value: trailing });
    return blocks;
  }

  function blockToTag(block) {
    switch (block.kind) {
      case "text":
        return block.value || "";
      case "align":
        return `[align:${block.value || "left"}]`;
      case "bold_toggle":
        return block.state === "off" ? "[/bold]" : "[bold]";
      case "hr":
        return "[hr]";
      case "blank":
        return "[blank]";
      case "newline":
        return "[newline]";
      case "date":
        return block.format ? `[date:${block.format}]` : "[date]";
      case "random":
        return block.digits && block.digits !== 6 ? `[random:${block.digits}]` : "[random]";
      case "print_number":
        return "[print_number]";
      case "counter":
        return block.key ? `[counter:${block.key}]` : "";
      case "image":
        return block.imageId ? `[image:${block.imageId}]` : "";
      case "cut":
        return block.feedBefore > 0
          ? `[cut:${block.value || "full"}:${block.feedBefore}]`
          : `[cut:${block.value || "full"}]`;
      case "drawer":
        return "[drawer]";
      case "feed":
        return `[feed:${block.lines || 4}]`;
      case "hex":
        return `[hex:${block.value || ""}]`;
      case "dec":
        return `[dec:${block.value || ""}]`;
      case "body":
        return "[body]";
      case "raw":
        return block.value || "";
      default:
        return "";
    }
  }

  function serializeBlocks(blocks) {
    return (blocks || []).map(blockToTag).join("");
  }

  // Positions the dragged item relative to another item's id rather than a
  // raw numeric index. A plain "insert at index N" is ambiguous once you
  // remove the dragged item first — the same target index means "before"
  // or "after" the hovered row depending on whether you dragged upward or
  // downward, which is exactly what made the old drag-and-drop impossible
  // to predict. Re-finding the target by id after removal sidesteps that:
  // "before/after this specific block" means the same thing regardless of
  // drag direction.
  function moveItemRelativeTo(items, fromId, targetId, placeAfter) {
    const fromIndex = items.findIndex((item) => item.id === fromId);
    if (fromIndex === -1) return items;
    const next = items.slice();
    const [moved] = next.splice(fromIndex, 1);
    if (targetId == null) {
      next.push(moved);
      return next;
    }
    const targetIndex = next.findIndex((item) => item.id === targetId);
    if (targetIndex === -1) {
      next.push(moved);
      return next;
    }
    next.splice(placeAfter ? targetIndex + 1 : targetIndex, 0, moved);
    return next;
  }

  function defaultBlockForKind(kind) {
    switch (kind) {
      case "align":
        return { kind: "align", value: "left" };
      case "bold_toggle":
        return { kind: "bold_toggle", state: "on" };
      case "hr":
        return { kind: "hr" };
      case "blank":
        return { kind: "blank" };
      case "newline":
        return { kind: "newline" };
      case "date":
        return { kind: "date", format: "" };
      case "print_number":
        return { kind: "print_number" };
      case "counter":
        return { kind: "counter", key: "" };
      case "random":
        return { kind: "random", digits: 6 };
      case "image":
        return { kind: "image", imageId: "" };
      case "cut":
        return { kind: "cut", value: "full", feedBefore: 4 };
      case "drawer":
        return { kind: "drawer" };
      case "feed":
        return { kind: "feed", lines: 4 };
      case "hex":
        return { kind: "hex", value: "" };
      case "dec":
        return { kind: "dec", value: "" };
      case "body":
        return { kind: "body" };
      case "text":
      default:
        return { kind: "text", value: "" };
    }
  }

  const DATE_FORMAT_PRESETS = [
    { value: "", label: "Date — 2026-07-28" },
    { value: "%d/%m/%Y", label: "Date (D/M/Y) — 28/07/2026" },
    { value: "%m/%d/%Y", label: "Date (M/D/Y) — 07/28/2026" },
    { value: "%H:%M", label: "Time, 24h — 14:35" },
    { value: "%H:%M:%S", label: "Time, 24h + seconds — 14:35:09" },
    { value: "%I:%M %p", label: "Time, 12h — 02:35 PM" },
    { value: "%Y-%m-%d %H:%M", label: "Date + time, 24h — 2026-07-28 14:35" },
    { value: "%Y-%m-%d %I:%M %p", label: "Date + time, 12h — 2026-07-28 02:35 PM" },
  ];

  // Almost every thermal receipt printer is 203 DPI; that's what these
  // presets and the live mm/in readout assume. It's a documented
  // approximation, not a per-printer measurement - there's no way to query
  // the printer's real DPI over a RAW connection.
  const PAPER_WIDTH_DPI = 203;
  const PAPER_WIDTH_PRESETS = [
    { value: 384, label: "58mm roll — 384 dots" },
    { value: 576, label: "80mm roll — 576 dots" },
  ];

  function dotsToPhysicalSizeLabel(dots) {
    const inches = dots / PAPER_WIDTH_DPI;
    const mm = inches * 25.4;
    return `≈ ${mm.toFixed(1)}mm / ${inches.toFixed(2)}in at ${PAPER_WIDTH_DPI} DPI`;
  }

  const ADD_BLOCK_KINDS = [
    "text",
    "body",
    "image",
    "align",
    "bold_toggle",
    "hr",
    "blank",
    "newline",
    "date",
    "print_number",
    "counter",
    "random",
    "cut",
    "drawer",
    "feed",
    "hex",
    "dec",
  ];

  function blockKindLabel(kind) {
    return (
      {
        text: S.receipt_block_text,
        body: S.receipt_block_body,
        image: S.receipt_block_image,
        align: S.receipt_block_align,
        bold_toggle: S.receipt_block_bold,
        hr: S.receipt_block_hr,
        blank: S.receipt_block_blank,
        newline: S.receipt_block_newline,
        date: S.receipt_block_date,
        print_number: S.receipt_block_print_number,
        counter: S.receipt_block_counter,
        random: S.receipt_block_random,
        cut: S.receipt_block_cut,
        drawer: S.receipt_block_drawer,
        feed: S.receipt_block_feed,
        hex: S.receipt_block_hex,
        dec: S.receipt_block_dec,
        raw: S.receipt_block_raw,
      }[kind] || kind
    );
  }

  // ------------------------------------------------------------------
  // Approximate CSS preview: turns the dry-run block list returned by
  // preview_receipt_template into a small number of "lines" the way an
  // ESC/POS align command really behaves (applies to everything printed
  // from that point until changed, not just one line) — not a literal
  // dot-matrix simulation.
  // ------------------------------------------------------------------
  function buildPreviewLines(blocks) {
    const lines = [];
    let align = "left";
    let bold = false;
    let current = { align, content: [] };
    // Flushing on an align/hr boundary should only emit a line if there's
    // actual content pending - an alignment change with nothing before it
    // shouldn't produce a spurious blank row. An explicit [blank]/[newline]
    // tag is different: it means "print an empty line" and must always
    // produce a visible line even when nothing has been added since the
    // last flush - the previous version used one flush for both cases and
    // silently dropped consecutive blank lines as a result.
    const flushIfNonEmpty = () => {
      if (current.content.length) lines.push(current);
      current = { align, content: [] };
    };
    const flushAlways = () => {
      lines.push(current);
      current = { align, content: [] };
    };
    (blocks || []).forEach((block) => {
      switch (block.type) {
        case "align":
          flushIfNonEmpty();
          align = block.value || "left";
          current.align = align;
          break;
        case "bold_start":
          bold = true;
          break;
        case "bold_end":
          bold = false;
          break;
        case "blank":
        case "newline":
          flushAlways();
          break;
        case "hr":
          flushIfNonEmpty();
          lines.push({ align: "center", content: [{ type: "hr", width: block.width || 32 }] });
          break;
        case "text":
          current.content.push({ type: "text", value: block.value, bold });
          break;
        case "image":
          current.content.push({ type: "image", image_id: block.image_id });
          break;
        case "marker":
          current.content.push({ type: "marker", label: block.label });
          break;
        case "body_placeholder":
          current.content.push({ type: "body_placeholder", implicit: !!block.implicit });
          break;
        default:
          break;
      }
    });
    flushIfNonEmpty();
    return lines;
  }

  function alignToJustify(align) {
    if (align === "center") return "center";
    if (align === "right") return "flex-end";
    return "flex-start";
  }

  function PreviewLines({ lines, images }) {
    if (!lines || lines.length === 0) {
      return html`<p class="hint-text">${S.receipt_no_blocks}</p>`;
    }
    const imageById = {};
    (images || []).forEach((image) => {
      imageById[image.id] = image;
    });
    return html`
      <div>
        ${lines.map(
          (line, i) => html`
            <div
              class="receipt-preview-line"
              style=${{ textAlign: line.align || "left", justifyContent: alignToJustify(line.align) }}
              key=${i}
            >
              ${line.content.map((item, j) => {
                if (item.type === "hr") {
                  return html`<span class="receipt-preview-hr" key=${j}>${"-".repeat(Math.max(1, item.width || 32))}</span>`;
                }
                if (item.type === "image") {
                  const image = imageById[item.image_id];
                  return image && image.data_base64
                    ? html`<img
                        class="receipt-preview-image"
                        key=${j}
                        src=${`data:image/png;base64,${image.data_base64}`}
                        alt=${image.name}
                      />`
                    : html`<span class="receipt-preview-marker" key=${j}>${S.receipt_block_image}</span>`;
                }
                if (item.type === "marker") {
                  return html`<span class="receipt-preview-marker" key=${j}>${item.label}</span>`;
                }
                if (item.type === "body_placeholder") {
                  return html`<span class="receipt-preview-body" key=${j}>${S.receipt_block_body}</span>`;
                }
                const style = { fontWeight: item.bold ? 700 : 400 };
                return html`<span key=${j} style=${style}>${item.value}</span>`;
              })}
            </div>
          `
        )}
      </div>
    `;
  }

  function BlockControls({ block, images, onChange }) {
    switch (block.kind) {
      case "body":
        return html`<small class="hint-text">${S.receipt_block_body_hint}</small>`;
      case "text":
        return html`<input
          type="text"
          value=${block.value}
          onInput=${(e) => onChange({ value: e.target.value })}
          placeholder=${S.receipt_block_text}
        />`;
      case "image":
        return html`
          <select value=${block.imageId} onChange=${(e) => onChange({ imageId: e.target.value })}>
            <option value="">—</option>
            ${(images || []).map((img) => html`<option value=${img.id}>${img.name}</option>`)}
          </select>
        `;
      case "align":
        return html`
          <select value=${block.value} onChange=${(e) => onChange({ value: e.target.value })}>
            <option value="left">${S.receipt_align_left}</option>
            <option value="center">${S.receipt_align_center}</option>
            <option value="right">${S.receipt_align_right}</option>
          </select>
        `;
      case "bold_toggle":
        return html`
          <select value=${block.state} onChange=${(e) => onChange({ state: e.target.value })}>
            <option value="on">${S.receipt_bold_on}</option>
            <option value="off">${S.receipt_bold_off}</option>
          </select>
        `;
      case "date": {
        const isKnownPreset = DATE_FORMAT_PRESETS.some((preset) => preset.value === block.format);
        return html`
          <select
            value=${isKnownPreset ? block.format : "__custom__"}
            onChange=${(e) => {
              if (e.target.value !== "__custom__") onChange({ format: e.target.value });
            }}
          >
            ${DATE_FORMAT_PRESETS.map((preset) => html`<option value=${preset.value}>${preset.label}</option>`)}
            <option value="__custom__">${S.receipt_date_format_custom}</option>
          </select>
          <input
            type="text"
            value=${block.format}
            onInput=${(e) => onChange({ format: e.target.value })}
            placeholder="%Y-%m-%d"
          />
        `;
      }
      case "random":
        return html`<input
          type="number"
          min="1"
          max="12"
          value=${block.digits}
          onInput=${(e) => onChange({ digits: parseInt(e.target.value, 10) || 6 })}
        />`;
      case "counter":
        return html`<input
          type="text"
          list="receipt-counter-keys"
          value=${block.key}
          onInput=${(e) => onChange({ key: e.target.value })}
          placeholder=${S.receipt_counter_name}
        />`;
      case "cut":
        return html`
          <select value=${block.value} onChange=${(e) => onChange({ value: e.target.value })}>
            <option value="full">${S.receipt_cut_full}</option>
            <option value="partial">${S.receipt_cut_partial}</option>
          </select>
          <input
            type="number"
            min="0"
            max="255"
            title=${S.receipt_cut_feed_before_hint}
            value=${block.feedBefore || 0}
            onInput=${(e) => onChange({ feedBefore: Math.max(0, parseInt(e.target.value, 10) || 0) })}
          />
          <small class="hint-text">${S.receipt_cut_feed_before_label}</small>
        `;
      case "feed":
        return html`<input
          type="number"
          min="1"
          max="255"
          value=${block.lines}
          onInput=${(e) => onChange({ lines: parseInt(e.target.value, 10) || 4 })}
        />`;
      case "hex":
        return html`<input
          type="text"
          value=${block.value}
          onInput=${(e) => onChange({ value: e.target.value })}
          placeholder="1D 56 00"
        />`;
      case "dec":
        return html`<input
          type="text"
          value=${block.value}
          onInput=${(e) => onChange({ value: e.target.value })}
          placeholder="29 86 0"
        />`;
      case "raw":
        return html`<input type="text" value=${block.value} disabled />`;
      default:
        return null;
    }
  }

  function BlockEditor({ title, blocks, onChange, images, draggingId, setDraggingId, previewLines }) {
    const [newKind, setNewKind] = useState("text");
    const [viewMode, setViewMode] = useState("blocks");
    const [textDraft, setTextDraft] = useState(() => serializeBlocks(blocks));
    // Where the dragged block will land if dropped right now: dropTargetId
    // is the block it's being positioned next to (null means "at the very
    // end"), dropAfter says which side of that block. Both are shown as a
    // highlighted insertion line so the landing spot is never a guess.
    const [dropTargetId, setDropTargetId] = useState(null);
    const [dropAfter, setDropAfter] = useState(false);

    useEffect(() => {
      if (viewMode !== "text") setTextDraft(serializeBlocks(blocks));
    }, [blocks, viewMode]);

    // These all use the functional setState form (onChange is the parent's
    // raw setHeaderBlocks/setFooterBlocks) rather than reading the `blocks`
    // prop directly. Reading `blocks` here would close over a snapshot that
    // can go stale if two edits land in the same render tick (e.g. adding
    // several blocks in quick succession) - React would then apply the
    // second update on top of the first's pre-update snapshot and silently
    // clobber it, which is what caused blocks to vanish or reorder for no
    // visible reason.
    const updateBlock = (id, patch) => {
      onChange((prev) => prev.map((b) => (b.id === id ? { ...b, ...patch } : b)));
    };
    const removeBlock = (id) => {
      onChange((prev) => prev.filter((b) => b.id !== id));
    };
    const addBlock = () => {
      onChange((prev) => [...prev, { id: uid(), ...defaultBlockForKind(newKind) }]);
    };
    const duplicateBlock = (id) => {
      onChange((prev) => {
        const index = prev.findIndex((b) => b.id === id);
        if (index === -1) return prev;
        const copy = { ...prev[index], id: uid() };
        const next = prev.slice();
        next.splice(index + 1, 0, copy);
        return next;
      });
    };
    const moveBlockBy = (id, delta) => {
      onChange((prev) => {
        const index = prev.findIndex((b) => b.id === id);
        const targetIndex = index + delta;
        if (index === -1 || targetIndex < 0 || targetIndex >= prev.length) return prev;
        const next = prev.slice();
        const [moved] = next.splice(index, 1);
        next.splice(targetIndex, 0, moved);
        return next;
      });
    };
    const clearDropTarget = () => {
      setDropTargetId(null);
      setDropAfter(false);
    };
    const hoverRow = (event, block) => {
      event.preventDefault();
      if (draggingId == null) return;
      const rect = event.currentTarget.getBoundingClientRect();
      const isAfter = event.clientY - rect.top > rect.height / 2;
      setDropTargetId(block.id);
      setDropAfter(isAfter);
    };
    const hoverEndZone = (event) => {
      event.preventDefault();
      if (draggingId == null) return;
      setDropTargetId(null);
      setDropAfter(false);
    };
    const finishDrop = (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (draggingId != null) {
        onChange((prev) => moveItemRelativeTo(prev, draggingId, dropTargetId, dropAfter));
      }
      setDraggingId(null);
      clearDropTarget();
    };
    const updateTextDraft = (value) => {
      setTextDraft(value);
      onChange(parseTemplate(value).map((b) => ({ id: uid(), ...b })));
    };

    return html`
      <div class="receipt-editor-block">
        <div class="receipt-editor-heading-row">
          <h3>${title}</h3>
          <div class="receipt-view-toggle">
            <button
              type="button"
              class=${viewMode === "blocks" ? "active" : ""}
              onClick=${() => setViewMode("blocks")}
            >
              ${S.receipt_view_blocks}
            </button>
            <button
              type="button"
              class=${viewMode === "text" ? "active" : ""}
              onClick=${() => setViewMode("text")}
            >
              ${S.receipt_view_text}
            </button>
          </div>
        </div>
        ${viewMode === "text"
          ? html`
              <textarea
                class="receipt-text-editor"
                value=${textDraft}
                onInput=${(e) => updateTextDraft(e.target.value)}
              ></textarea>
              <p class="field-hint">${S.receipt_text_edit_hint}</p>
            `
          : html`
              <div class="receipt-add-block-row">
                <select value=${newKind} onChange=${(e) => setNewKind(e.target.value)}>
                  ${ADD_BLOCK_KINDS.map((kind) => html`<option value=${kind}>${blockKindLabel(kind)}</option>`)}
                </select>
                <button class="btn-secondary" onClick=${addBlock}>${S.receipt_add_block}</button>
              </div>
              <div class="receipt-block-list" onDrop=${finishDrop}>
                ${blocks.length === 0 ? html`<p class="hint-text">${S.receipt_no_blocks}</p>` : null}
                ${blocks.map(
                  (block, index) => html`
                    <div
                      class=${[
                        "receipt-block-row",
                        draggingId === block.id ? "receipt-block-row-dragging" : "",
                        dropTargetId === block.id && !dropAfter ? "receipt-block-drop-before" : "",
                        dropTargetId === block.id && dropAfter ? "receipt-block-drop-after" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      key=${block.id}
                      onDragOver=${(event) => hoverRow(event, block)}
                      onDrop=${finishDrop}
                    >
                      <span
                        class="widget-drag-handle"
                        draggable="true"
                        title=${S.drag_to_reorder}
                        onDragStart=${(event) => {
                          event.dataTransfer.effectAllowed = "move";
                          setDraggingId(block.id);
                        }}
                        onDragEnd=${() => {
                          setDraggingId(null);
                          clearDropTarget();
                        }}
                      >⋮⋮</span>
                      <div class="dnd-move-buttons">
                        <button
                          type="button"
                          class="dnd-move-btn"
                          title=${S.receipt_move_up}
                          disabled=${index === 0}
                          onClick=${() => moveBlockBy(block.id, -1)}
                        >▲</button>
                        <button
                          type="button"
                          class="dnd-move-btn"
                          title=${S.receipt_move_down}
                          disabled=${index === blocks.length - 1}
                          onClick=${() => moveBlockBy(block.id, 1)}
                        >▼</button>
                      </div>
                      <span class="receipt-block-kind-label">${blockKindLabel(block.kind)}</span>
                      <div class="receipt-block-controls">
                        <${BlockControls} block=${block} images=${images} onChange=${(patch) => updateBlock(block.id, patch)} />
                      </div>
                      <button class="btn-secondary" title=${S.receipt_duplicate_block} onClick=${() => duplicateBlock(block.id)}>${S.receipt_duplicate_block}</button>
                      <button class="btn-danger-small" onClick=${() => removeBlock(block.id)}>${S.receipt_remove_block}</button>
                    </div>
                  `
                )}
                ${draggingId != null
                  ? html`
                      <div
                        class=${"receipt-block-drop-end" + (dropTargetId === null ? " receipt-block-drop-end-active" : "")}
                        onDragOver=${hoverEndZone}
                        onDrop=${finishDrop}
                      >
                        ${S.receipt_drop_at_end}
                      </div>
                    `
                  : null}
              </div>
            `}
        <h3>${S.receipt_preview}</h3>
        <div class="receipt-preview-panel">
          <${PreviewLines} lines=${previewLines} images=${images} />
        </div>
      </div>
    `;
  }

  function shortcodeGuideGroups() {
    return [
      {
        title: S.receipt_guide_category_text,
        items: [
          { tag: "[body]", desc: S.receipt_guide_body_desc },
          { tag: "[align:left]  [align:center]  [align:right]", desc: S.receipt_guide_align_desc },
          { tag: "[bold]...[/bold]", desc: S.receipt_guide_bold_desc },
          { tag: "[hr]", desc: S.receipt_guide_hr_desc },
          { tag: "[blank]", desc: S.receipt_guide_blank_desc },
          { tag: "[newline]", desc: S.receipt_guide_newline_desc },
        ],
      },
      {
        title: S.receipt_guide_category_dynamic,
        items: [
          { tag: "[date]", desc: S.receipt_guide_date_desc },
          { tag: "[date:FORMAT]", desc: S.receipt_guide_date_format_desc },
          { tag: "[random]  [random:N]", desc: S.receipt_guide_random_desc },
          { tag: "[print_number]", desc: S.receipt_guide_print_number_desc },
          { tag: "[counter:name]", desc: S.receipt_guide_counter_desc },
        ],
      },
      {
        title: S.receipt_guide_category_images,
        items: [{ tag: "[image:id]", desc: S.receipt_guide_image_desc }],
      },
      {
        title: S.receipt_guide_category_commands,
        items: [
          { tag: "[cut:full]  [cut:partial]  [cut:full:6]", desc: S.receipt_guide_cut_desc },
          { tag: "[drawer]", desc: S.receipt_guide_drawer_desc },
          { tag: "[feed]  [feed:N]", desc: S.receipt_guide_feed_desc },
          { tag: "[hex:1D 56 00]", desc: S.receipt_guide_hex_desc },
          { tag: "[dec:29 86 0]", desc: S.receipt_guide_dec_desc },
        ],
      },
    ];
  }

  function ShortcodeGuide() {
    return html`
      <details class="receipt-guide">
        <summary>${S.receipt_guide_title}</summary>
        <div class="receipt-guide-body">
          <p class="hint-text">${S.receipt_guide_intro}</p>
          ${shortcodeGuideGroups().map(
            (group) => html`
              <div class="receipt-guide-group" key=${group.title}>
                <h4>${group.title}</h4>
                <dl class="receipt-guide-list">
                  ${group.items.map(
                    (item) => html`
                      <dt key=${item.tag + "-dt"}><code>${item.tag}</code></dt>
                      <dd key=${item.tag + "-dd"}>${item.desc}</dd>
                    `
                  )}
                </dl>
              </div>
            `
          )}
        </div>
      </details>
    `;
  }

  // Flattens every server's printer_mappings (already in get_state) into one
  // list. Composer content is scoped per mapping now, not per printer - a
  // printer with no mappings has no entry here at all, and a printer mapped
  // from 3 endpoints shows up 3 times, once per mapping.
  function flattenMappings(servers) {
    const flattened = [];
    (servers || []).forEach((server) => {
      (server.printer_mappings || []).forEach((mapping) => {
        flattened.push({
          serverId: server.id,
          serverName: server.name,
          remotePrinterId: mapping.remote_printer_id,
          remotePrinterName: mapping.remote_printer_name,
          localPrinterName: mapping.local_printer_name,
        });
      });
    });
    return flattened;
  }

  function mappingLabel(mapping) {
    const remoteLabel = mapping.remotePrinterName || mapping.remotePrinterId;
    return `${mapping.serverName} — ${remoteLabel} → ${mapping.localPrinterName}`;
  }

  function ReceiptComposer() {
    const [mappings, setMappings] = useState([]);
    const [selectedIndex, setSelectedIndex] = useState("");
    const [design, setDesign] = useState(null);
    const [printerMode, setPrinterMode] = useState("");
    const [templateBlocks, setTemplateBlocks] = useState([]);
    const [images, setImages] = useState([]);
    const [counters, setCounters] = useState({});
    const [draggingId, setDraggingId] = useState(null);
    const [uploadingImage, setUploadingImage] = useState(false);
    const [message, setMessage] = useState("");
    const [templatePreview, setTemplatePreview] = useState([]);
    const [newCounterKey, setNewCounterKey] = useState("");
    const [newCounterLabel, setNewCounterLabel] = useState("");
    const [testBusy, setTestBusy] = useState(false);
    const saveTimer = useRef(null);
    const previewTimer = useRef(null);
    const skipNextSave = useRef(false);

    const selectedMapping = selectedIndex === "" ? null : mappings[parseInt(selectedIndex, 10)];

    const refreshImages = () => {
      callApi("get_receipt_images").then((result) => {
        if (result && result.ok) setImages(result.images);
      });
    };

    const refreshCounters = (mapping) => {
      if (!mapping) return;
      callApi("get_receipt_counters", mapping.serverId, mapping.remotePrinterId).then((result) => {
        if (result && result.ok) setCounters(result.counters);
      });
    };

    // Selecting by index (not by the mapping object itself) so this can be
    // driven either by the <select>'s onChange (index as a string) or by the
    // pending-selection deep link below (index resolved by matching ids).
    const selectMappingAt = (index) => {
      const mapping = mappings[index];
      if (!mapping) {
        setSelectedIndex("");
        setDesign(null);
        setPrinterMode("");
        setTemplateBlocks([]);
        setCounters({});
        return;
      }
      setSelectedIndex(String(index));
      callApi("get_mapping_receipt_design", mapping.serverId, mapping.remotePrinterId).then((result) => {
        if (!result || !result.ok) return;
        skipNextSave.current = true;
        setDesign(result.design);
        setPrinterMode(result.printer_mode);
        // A brand-new mapping with no saved design starts from a single Body
        // block rather than a blank list, so it's immediately obvious where
        // the incoming print content goes before any decoration is added.
        const parsed = parseTemplate(result.design.raw_template);
        setTemplateBlocks((parsed.length ? parsed : [{ kind: "body" }]).map((b) => ({ id: uid(), ...b })));
        refreshCounters(mapping);
      });
    };

    const selectMapping = (event) => {
      const value = event.target.value;
      if (value === "") {
        selectMappingAt(-1);
        return;
      }
      selectMappingAt(parseInt(value, 10));
    };

    // Opening the Composer window scoped to one specific mapping (the
    // dashboard widget's edit-pencil button) works by having gui.py stash a
    // (server_id, remote_printer_id) pair that this checks for once on
    // mount. `mappingList` is passed explicitly rather than read off the
    // `mappings` state variable, since right after get_state resolves at
    // mount time that state hasn't committed yet.
    const applyPendingSelection = (mappingList) => {
      callApi("get_pending_receipt_selection").then((result) => {
        if (!result || !result.ok || !result.server_id || !result.remote_printer_id) return;
        const index = mappingList.findIndex(
          (mapping) => mapping.serverId === result.server_id && mapping.remotePrinterId === result.remote_printer_id
        );
        if (index !== -1) selectMappingAt(index);
      });
    };

    useEffect(() => {
      whenApiReady(() => {
        callApi("get_state").then((result) => {
          if (!result) return;
          if (result.state.appearance) {
            document.documentElement.dataset.darkness = (result.state.appearance.darkness_grade || "Onyx").toLowerCase();
          }
          const mappingList = flattenMappings(result.state.servers);
          setMappings(mappingList);
          applyPendingSelection(mappingList);
        });
        refreshImages();
      });
    }, []);

    // Re-checks the pending selection when the Composer window was already
    // open (open_receipt_composer_window's evaluate_js nudge calls this) -
    // the mount-time effect above only ever runs once per window lifetime,
    // so a second "Edit" click while the window is still open needs this
    // separate hook back in.
    useEffect(() => {
      window.__pridgeApplyPendingReceiptSelection = () => applyPendingSelection(mappings);
      return () => {
        delete window.__pridgeApplyPendingReceiptSelection;
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [mappings]);

    const testMapping = () => {
      if (!selectedMapping) return;
      setTestBusy(true);
      setMessage("");
      callApi("test_mapping_receipt_design", selectedMapping.serverId, selectedMapping.remotePrinterId).then((result) => {
        setTestBusy(false);
        if (!result) return;
        setMessage(result.ok ? result.message || S.test_print_submitted : result.error || S.test_print_failed);
        if (result.ok) refreshCounters(selectedMapping);
      });
    };

    useEffect(() => {
      if (!selectedMapping || !design) return undefined;
      if (skipNextSave.current) {
        skipNextSave.current = false;
        return undefined;
      }
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => {
        callApi("update_mapping_receipt_design", selectedMapping.serverId, selectedMapping.remotePrinterId, {
          raw_template: serializeBlocks(templateBlocks),
          raw_paper_width_dots: design.raw_paper_width_dots,
          raw_chars_per_line: design.raw_chars_per_line,
        }).then((result) => {
          if (result && result.ok) setMessage(S.settings_saved_automatically);
        });
      }, 500);
      return () => window.clearTimeout(saveTimer.current);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [templateBlocks, design]);

    useEffect(() => {
      if (!selectedMapping) {
        setTemplatePreview([]);
        return undefined;
      }
      if (previewTimer.current) clearTimeout(previewTimer.current);
      previewTimer.current = window.setTimeout(() => {
        callApi(
          "preview_receipt_template",
          serializeBlocks(templateBlocks),
          selectedMapping.serverId,
          selectedMapping.remotePrinterId
        ).then((result) => {
          if (result && result.ok) setTemplatePreview(buildPreviewLines(result.blocks));
        });
      }, 250);
      return () => window.clearTimeout(previewTimer.current);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [templateBlocks, selectedIndex]);

    const uploadImage = (event) => {
      const file = event.target.files && event.target.files[0];
      event.target.value = "";
      if (!file) return;
      setUploadingImage(true);
      const reader = new FileReader();
      reader.onload = () => {
        const base64 = String(reader.result).split(",")[1] || "";
        callApi("add_receipt_image", file.name.replace(/\.[^.]+$/, ""), base64).then((result) => {
          setUploadingImage(false);
          if (result && result.ok) {
            setImages(result.images);
          } else {
            setMessage((result && result.error) || S.receipt_image_add_failed);
          }
        });
      };
      reader.onerror = () => setUploadingImage(false);
      reader.readAsDataURL(file);
    };

    const removeImage = (imageId, name) => {
      if (!window.confirm(S.receipt_remove_image_confirm.replace("{name}", name))) return;
      callApi("remove_receipt_image", imageId).then((result) => {
        if (result && result.ok) setImages(result.images);
      });
    };

    const addCounter = () => {
      const key = newCounterKey.trim();
      if (!key || !selectedMapping) return;
      callApi("add_receipt_counter", selectedMapping.serverId, selectedMapping.remotePrinterId, key, newCounterLabel.trim()).then(
        (result) => {
          if (result && result.ok) {
            setCounters(result.counters);
            setNewCounterKey("");
            setNewCounterLabel("");
          } else {
            setMessage((result && result.error) || S.receipt_counter_add_failed);
          }
        }
      );
    };

    const resetCounter = (key, label) => {
      if (!selectedMapping) return;
      const input = window.prompt(S.receipt_reset_counter_prompt.replace("{name}", label || key), "0");
      if (input === null) return;
      const value = parseInt(input, 10);
      callApi(
        "reset_receipt_counter",
        selectedMapping.serverId,
        selectedMapping.remotePrinterId,
        key,
        Number.isFinite(value) ? value : 0
      ).then((result) => {
        if (result && result.ok) setCounters(result.counters);
      });
    };

    const removeCounter = (key, label) => {
      if (!selectedMapping) return;
      if (!window.confirm(S.receipt_remove_counter_confirm.replace("{name}", label || key))) return;
      callApi("remove_receipt_counter", selectedMapping.serverId, selectedMapping.remotePrinterId, key).then((result) => {
        if (result && result.ok) setCounters(result.counters);
      });
    };

    const defaultCounterValue = (counters.__default__ && counters.__default__.value) || 0;
    const namedCounterKeys = Object.keys(counters)
      .filter((key) => key !== "__default__")
      .sort();

    return html`
      <main class="utility-page">
        <datalist id="receipt-counter-keys">
          ${namedCounterKeys.map((key) => html`<option value=${key}></option>`)}
        </datalist>
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.receipt_composer}</h1><p>${S.receipt_composer_hint}</p></div>
        </div>
        <div class="utility-content">
          <${ShortcodeGuide} />
          <section class="settings-section">
            <div class="field">
              <label class="field-label">${S.receipt_composer_select_mapping}</label>
              <div class="field-row">
                <select value=${selectedIndex} onChange=${selectMapping}>
                  <option value="">—</option>
                  ${mappings.map(
                    (mapping, index) => html`<option value=${index} key=${index}>${mappingLabel(mapping)}</option>`
                  )}
                </select>
                <button
                  type="button"
                  class="btn-secondary"
                  onClick=${testMapping}
                  disabled=${!selectedMapping || !design || printerMode !== "raw" || testBusy}
                >
                  ${testBusy ? S.working : S.receipt_test_print}
                </button>
              </div>
              ${selectedMapping && design && printerMode !== "raw"
                ? html`<small class="field-hint">${S.receipt_test_print_raw_only}</small>`
                : null}
            </div>
            ${mappings.length === 0 ? html`<p class="hint-text">${S.receipt_composer_no_mappings}</p>` : null}

            ${!selectedMapping || !design
              ? html`<p class="hint-text">${S.receipt_select_mapping_first}</p>`
              : html`
                  <div class="receipt-numeric-fields">
                    <div class="field">
                      <label class="field-label">${S.receipt_paper_width}</label>
                      <select
                        value=${PAPER_WIDTH_PRESETS.some((preset) => preset.value === design.raw_paper_width_dots)
                          ? design.raw_paper_width_dots
                          : "__custom__"}
                        onChange=${(e) => {
                          if (e.target.value === "__custom__") return;
                          setDesign({ ...design, raw_paper_width_dots: parseInt(e.target.value, 10) });
                        }}
                      >
                        ${PAPER_WIDTH_PRESETS.map(
                          (preset) => html`<option value=${preset.value}>${preset.label}</option>`
                        )}
                        <option value="__custom__">${S.receipt_paper_width_custom}</option>
                      </select>
                      <input
                        type="number"
                        min="8"
                        step="8"
                        value=${design.raw_paper_width_dots}
                        onInput=${(e) => setDesign({ ...design, raw_paper_width_dots: parseInt(e.target.value, 10) || 384 })}
                      />
                      <small class="field-hint">${dotsToPhysicalSizeLabel(design.raw_paper_width_dots)}</small>
                    </div>
                    <div class="field">
                      <label class="field-label">${S.receipt_chars_per_line}</label>
                      <input
                        type="number"
                        min="8"
                        max="128"
                        value=${design.raw_chars_per_line}
                        onInput=${(e) => setDesign({ ...design, raw_chars_per_line: parseInt(e.target.value, 10) || 32 })}
                      />
                    </div>
                  </div>

                  <${BlockEditor}
                    key=${selectedIndex + "-template"}
                    title=${S.receipt_design}
                    blocks=${templateBlocks}
                    onChange=${setTemplateBlocks}
                    images=${images}
                    draggingId=${draggingId}
                    setDraggingId=${setDraggingId}
                    previewLines=${templatePreview}
                  />
                `}
          </section>

          <section class="settings-section">
            <h2>${S.receipt_images}</h2>
            <p>${S.receipt_images_hint}</p>
            <div class="receipt-image-grid">
              ${images.length === 0 ? html`<p class="hint-text">${S.receipt_no_images}</p>` : null}
              ${images.map(
                (image) => html`
                  <div class="receipt-image-card" key=${image.id}>
                    ${image.data_base64
                      ? html`<img src=${`data:image/png;base64,${image.data_base64}`} alt=${image.name} />`
                      : null}
                    <small>${image.name}</small>
                    <small>${image.width}×${image.height}px</small>
                    <button class="btn-danger-small" onClick=${() => removeImage(image.id, image.name)}>${S.remove}</button>
                  </div>
                `
              )}
            </div>
            <label class="btn-secondary receipt-upload-label">
              ${uploadingImage ? S.receipt_uploading_image : S.receipt_upload_image}
              <input type="file" accept="image/*" class="receipt-upload-input" onChange=${uploadImage} disabled=${uploadingImage} />
            </label>
          </section>

          ${selectedMapping
            ? html`
                <section class="settings-section">
                  <h2>${S.receipt_counters}</h2>
                  <p>${S.receipt_counters_hint}</p>
                  <div class="receipt-counter-row">
                    <div class="receipt-counter-copy">
                      <strong>${S.receipt_default_counter_label}</strong>
                      <small>${defaultCounterValue}</small>
                    </div>
                    <button
                      class="btn-secondary"
                      onClick=${() => resetCounter("__default__", S.receipt_default_counter_label)}
                    >
                      ${S.receipt_reset}
                    </button>
                  </div>
                  ${namedCounterKeys.map(
                    (key) => html`
                      <div class="receipt-counter-row" key=${key}>
                        <div class="receipt-counter-copy">
                          <strong>${counters[key].label || key}</strong>
                          <small>${counters[key].value}</small>
                        </div>
                        <button class="btn-secondary" onClick=${() => resetCounter(key, counters[key].label)}>
                          ${S.receipt_reset}
                        </button>
                        <button class="btn-danger-small" onClick=${() => removeCounter(key, counters[key].label)}>
                          ${S.remove}
                        </button>
                      </div>
                    `
                  )}
                  <div class="receipt-counter-add-row">
                    <input
                      type="text"
                      value=${newCounterKey}
                      onInput=${(e) => setNewCounterKey(e.target.value)}
                      placeholder=${S.receipt_counter_name}
                    />
                    <input
                      type="text"
                      value=${newCounterLabel}
                      onInput=${(e) => setNewCounterLabel(e.target.value)}
                      placeholder=${S.receipt_counter_label_placeholder}
                    />
                    <button class="btn-secondary" onClick=${addCounter}>${S.receipt_add_counter}</button>
                  </div>
                </section>
              `
            : null}
        </div>
        <div class="utility-actions">
          <span class="utility-footer-info">${message}</span>
          <button onClick=${() => callApi("close_utility_window", "receipt_composer")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${ReceiptComposer} />`);
})();
