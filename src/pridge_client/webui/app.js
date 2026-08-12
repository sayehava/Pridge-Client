/*
 * SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.
 */

(() => {
  "use strict";

  const { useState, useEffect, useCallback, useRef } = React;
  const html = htm.bind(React.createElement);
  const S = window.PridgeStrings;
  const POLL_MS = 2000;
  const WIDGET_ALL_TAB = "__all__";

  function callApi(name, ...args) {
    if (!window.pywebview || !window.pywebview.api || !window.pywebview.api[name]) {
      return Promise.resolve(null);
    }
    return window.pywebview.api[name](...args);
  }

  function whenApiReady(callback, attempts = 0) {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.get_state) {
      callback();
      return;
    }
    if (attempts < 200) {
      window.setTimeout(() => whenApiReady(callback, attempts + 1), 50);
    }
  }

  function applyAppearance(state) {
    if (!state || !state.appearance) return;
    document.documentElement.dataset.darkness = (state.appearance.darkness_grade || "Onyx").toLowerCase();
  }

  // Resolves where a drag-and-drop reorder should land: `items` is the
  // current list, `fromId` the dragged item's id, `targetId` the item it's
  // hovering over (null = the end), `placeAfter` which side of the target.
  // Returns the resulting index in post-removal terms, which is what
  // reorder_dashboard_widget expects - computed this way (id-relative, not
  // a raw hovered-row index) so the same target always means the same
  // thing regardless of which direction the drag came from.
  function resolveDropIndex(items, fromId, targetId, placeAfter) {
    const withoutDragged = items.filter((item) => item.id !== fromId);
    if (targetId == null) return withoutDragged.length;
    const targetIndex = withoutDragged.findIndex((item) => item.id === targetId);
    return targetIndex === -1 ? withoutDragged.length : placeAfter ? targetIndex + 1 : targetIndex;
  }

  function Badge({ text, active = false }) {
    return html`<span class=${active ? "badge badge-active" : "badge"}>${text}</span>`;
  }

  function Sidebar({ state, onPlugins, onServers, onPrinters, onHistory, onSettings, onAbout, onQuit }) {
    return html`
      <div class="sidebar">
        <div class="sidebar-title">${state.app_name}</div>
        <div class="sidebar-version">v${state.version}</div>
        <div class="status-card">
          <div class="status-card-label">${S.status}</div>
          <div class="status-card-value">${state.ready_status}</div>
        </div>
        <div class="sidebar-spacer"></div>
        <div class="sidebar-footer">
          <button class="sidebar-nav full-width" onClick=${onPlugins}><span aria-hidden="true">🧩</span>${S.plugins}</button>
          <button class="sidebar-nav full-width" onClick=${onServers}><span aria-hidden="true">🖧</span>${S.servers}</button>
          <button class="sidebar-nav full-width" onClick=${onPrinters}><span aria-hidden="true">🖨</span>${S.printers}</button>
          <button class="sidebar-nav full-width" onClick=${onHistory}><span aria-hidden="true">🕘</span>${S.history}</button>
          <button class="sidebar-nav full-width" onClick=${onSettings}><span aria-hidden="true">⚙</span>${S.settings}</button>
          <button class="sidebar-nav full-width" onClick=${onAbout}><span aria-hidden="true">ⓘ</span>${S.about}</button>
          <button class="danger full-width" onClick=${onQuit}>${S.quit}</button>
        </div>
      </div>
    `;
  }

  function StatusBar({ state, onStart, onStop }) {
    return html`
      <div class="status-bar">
        <div class="status-bar-copy">
          <strong>${S.endpoint_controls}</strong>
          <span>${S.endpoint_controls_hint}</span>
        </div>
        <div class="badge-row"><label class="field-label">${S.connection_status}</label><${Badge} text=${state.connection_status} /></div>
        <div class="badge-row"><label class="field-label">${S.heartbeat}</label><${Badge} text=${state.heartbeat_status} /></div>
        <div class="button-row">
          <button class="success" onClick=${onStart}>${S.start_all}</button>
          <button class="danger" onClick=${onStop}>${S.stop_all}</button>
        </div>
      </div>
    `;
  }

  const SERVER_STATUS_ROTATE_MS = 6000;

  function trackedServers(widget, servers) {
    const ids = Array.isArray(widget.config && widget.config.server_ids) ? widget.config.server_ids : [];
    return ids.map((id) => servers.find((server) => server.id === id)).filter(Boolean);
  }

  function isServerErrored(server) {
    return !!server && typeof server.status === "string" && server.status.indexOf("Retrying after error") === 0;
  }

  function formatHeartbeat(iso) {
    if (!iso) return S.server_status_no_heartbeat;
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? S.server_status_no_heartbeat : date.toLocaleTimeString();
  }

  function isConfiguredWithAServer(printer, servers) {
    return (servers || []).some(
      (server) =>
        server.default_printer === printer.name ||
        (server.printer_mappings || []).some((mapping) => mapping.local_printer_name === printer.name)
    );
  }

  function ServerStatusWidget({ widget, servers }) {
    const tracked = trackedServers(widget, servers);
    const [pageIndex, setPageIndex] = useState(0);
    const alertedServerId = useRef(null);
    const currentPage = tracked.length > 0 ? Math.min(pageIndex, tracked.length - 1) : 0;
    const current = tracked[currentPage] || null;

    useEffect(() => {
      if (tracked.length === 0) return;
      const erroredIndex = tracked.findIndex(isServerErrored);
      if (erroredIndex === -1) {
        alertedServerId.current = null;
        return;
      }
      if (alertedServerId.current !== tracked[erroredIndex].id) {
        alertedServerId.current = tracked[erroredIndex].id;
        setPageIndex(erroredIndex);
      }
    }, [tracked]);

    useEffect(() => {
      if (!widget.config || !widget.config.auto_rotate || tracked.length < 2) return undefined;
      const id = window.setInterval(() => {
        setPageIndex((current) => (current + 1) % tracked.length);
      }, SERVER_STATUS_ROTATE_MS);
      return () => window.clearInterval(id);
    }, [widget.config && widget.config.auto_rotate, tracked.length]);

    if (tracked.length === 0) {
      return html`
        <div class="widget-server-status-empty">
          <strong>${S.server_status_none_selected}</strong>
          <span>${S.server_status_none_selected_hint}</span>
        </div>
      `;
    }

    return html`
      <div class="widget-server-status">
        <div class="widget-server-status-item">
          <div class="widget-server-status-heading">
            <span class="server-name">${current.name}</span>
            <${Badge} text=${current.status} active=${current.running} />
          </div>
          <div class="widget-server-status-meta">
            <span>${S.server_status_heartbeat}: ${formatHeartbeat(current.last_heartbeat_at)}</span>
            <span>${S.server_status_polling_every.replace("{seconds}", current.polling_interval_seconds)}</span>
          </div>
        </div>
        ${tracked.length > 1
          ? html`<div class="widget-server-status-dots">
              ${tracked.map(
                (server, index) => html`
                  <button
                    class=${"widget-server-status-dot" + (index === currentPage ? " active" : "") + (isServerErrored(server) ? " alert" : "")}
                    key=${server.id}
                    aria-label=${server.name}
                    onClick=${() => setPageIndex(index)}
                  />
                `
              )}
            </div>`
          : null}
      </div>
    `;
  }

  // Mirrors receipt-composer.js's own mapping flattening/labeling so the
  // dashboard widget and the Composer window agree on what a "mapping" is
  // and how it's displayed, without importing across the two page bundles.
  function flattenReceiptItems(servers) {
    const flattened = [];
    (servers || []).forEach((server) => {
      (server.printer_mappings || []).forEach((mapping) => {
        flattened.push({
          serverId: server.id,
          serverName: server.name,
          remotePrinterId: mapping.remote_printer_id,
          remotePrinterName: mapping.remote_printer_name,
          localPrinterName: mapping.local_printer_name,
          hasDesign: !!mapping.has_receipt_design,
        });
      });
    });
    return flattened;
  }

  function receiptItemLabel(item) {
    const remoteLabel = item.remotePrinterName || item.remotePrinterId;
    return `${item.serverName} — ${remoteLabel} → ${item.localPrinterName}`;
  }

  function ReceiptComposerWidget({ servers }) {
    // Removing an item updates the saved config immediately, but this
    // widget's own view of `servers` only catches up on the dashboard's
    // next ~2s poll tick, same as every other widget here (e.g. Server
    // Status) that reads live data out of the polled `servers` prop rather
    // than keeping its own copy.
    const items = flattenReceiptItems(servers).filter((item) => item.hasDesign);

    const openComposer = (item) => {
      if (item) callApi("open_receipt_composer_window", item.serverId, item.remotePrinterId);
      else callApi("open_receipt_composer_window");
    };

    const removeItem = (item) => {
      if (!window.confirm(S.receipt_widget_remove_confirm.replace("{name}", receiptItemLabel(item)))) return;
      callApi("clear_mapping_receipt_design", item.serverId, item.remotePrinterId);
    };

    return html`
      <div class="widget-receipt-composer">
        <div class="widget-receipt-composer-header">
          <span>${S.receipt_widget_items_label}</span>
          <button class="widget-receipt-add-btn" title=${S.receipt_widget_add} onClick=${() => openComposer(null)}>+</button>
        </div>
        ${items.length === 0
          ? html`<div class="scroll-panel empty">${S.receipt_widget_empty}</div>`
          : html`<div class="scroll-panel">
              ${items.map(
                (item) => html`
                  <div class="widget-receipt-item" key=${item.serverId + "::" + item.remotePrinterId}>
                    <span class="widget-receipt-item-label" title=${receiptItemLabel(item)}>${receiptItemLabel(item)}</span>
                    <button class="widget-receipt-edit-btn" title=${S.edit} onClick=${() => openComposer(item)}>✎</button>
                    <button class="widget-receipt-remove-btn" title=${S.remove} onClick=${() => removeItem(item)}>×</button>
                  </div>
                `
              )}
            </div>`}
      </div>
    `;
  }

  function LogsPanel({ logs }) {
    const panelRef = useRef(null);
    useEffect(() => {
      const element = panelRef.current;
      if (element) element.scrollTop = element.scrollHeight;
    }, [logs]);

    return logs.length === 0
      ? html`<div class="scroll-panel empty">${S.no_logs}</div>`
      : html`<div class="scroll-panel" ref=${panelRef}>
          ${logs.map((line, index) => html`<div class="log-line" key=${index}>${line}</div>`)}
        </div>`;
  }

  function ErrorLogPanel({ errorDetails }) {
    const panelRef = useRef(null);
    const [copied, setCopied] = useState(false);
    useEffect(() => {
      const element = panelRef.current;
      if (element) element.scrollTop = element.scrollHeight;
    }, [errorDetails]);

    const copyAll = () => {
      const text = errorDetails.join("\n\n");
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }
    };

    return html`
      <div class="error-log-widget">
        <div class="error-log-toolbar">
          <button onClick=${copyAll} disabled=${errorDetails.length === 0}>${copied ? S.copied : S.copy}</button>
        </div>
        ${errorDetails.length === 0
          ? html`<div class="scroll-panel empty">${S.no_error_details}</div>`
          : html`<div class="scroll-panel" ref=${panelRef}>
              ${errorDetails.map((entry, index) => html`<pre class="error-log-entry" key=${index}>${entry}</pre>`)}
            </div>`}
      </div>
    `;
  }

  function WidgetCard({
    widget,
    recentJobs,
    logs,
    errorDetails,
    printerDetails,
    servers,
    onRemove,
    onConfigure,
    isDragging,
    dropPosition,
    canMoveUp,
    canMoveDown,
    onDragStart,
    onDragEnd,
    onDragOverCard,
    onDropOn,
    onMoveUp,
    onMoveDown,
  }) {
    const containerId = `pridge-widget-${widget.id}`;
    const scriptLoaded = useRef(false);
    const hasAlert = widget.widget_type === "server_status" && trackedServers(widget, servers).some(isServerErrored);

    useEffect(() => {
      if (widget.source !== "plugin" || !widget.script_source || scriptLoaded.current) return;
      scriptLoaded.current = true;
      window.PridgeWidgetContainerId = containerId;
      const script = document.createElement("script");
      script.textContent = widget.script_source;
      document.body.appendChild(script);
    }, [widget.source, widget.script_source]);

    let body;
    if (widget.widget_type === "recent_jobs") {
      body = recentJobs.length === 0
        ? html`<div class="scroll-panel empty">${S.no_jobs}</div>`
        : html`<div class="scroll-panel">${recentJobs.map((line, i) => html`<div class="job-line" key=${i}>${line}</div>`)}</div>`;
    } else if (widget.widget_type === "logs") {
      body = html`<${LogsPanel} logs=${logs} />`;
    } else if (widget.widget_type === "error_log") {
      body = html`<${ErrorLogPanel} errorDetails=${errorDetails} />`;
    } else if (widget.widget_type === "printer_stats") {
      const usedOnly = !!(widget.config && widget.config.used_only);
      const visiblePrinters = usedOnly
        ? printerDetails.filter((printer) => isConfiguredWithAServer(printer, servers))
        : printerDetails;
      body = visiblePrinters.length === 0
        ? html`<div class="scroll-panel empty">${usedOnly ? S.no_used_printers : S.no_printers}</div>`
        : html`<div class="scroll-panel">
            ${visiblePrinters.map(
              (printer) => html`
                <div class="printer-stat-group" key=${printer.name}>
                  <div class="printer-stat-name">${printer.name}</div>
                  <div class="printer-stat-row">
                    <span class="printer-stat-label">${S.test_print}</span>
                    <span class="printer-stat-tiers">
                      <span class="printer-stat-tier">
                        <span class="printer-stat-tier-label">${S.stats_total}</span>
                        <span class="printer-stat-counts">
                          <span class="printer-stat-success">${printer.test_success_count}</span>
                          <span class="printer-stat-failed">${printer.test_failed_count}</span>
                        </span>
                      </span>
                      <span class="printer-stat-tier">
                        <span class="printer-stat-tier-label">${S.stats_session}</span>
                        <span class="printer-stat-counts">
                          <span class="printer-stat-success">${printer.session_test_success_count}</span>
                          <span class="printer-stat-failed">${printer.session_test_failed_count}</span>
                        </span>
                      </span>
                    </span>
                  </div>
                  <div class="printer-stat-row">
                    <span class="printer-stat-label">${S.remote_prints}</span>
                    <span class="printer-stat-tiers">
                      <span class="printer-stat-tier">
                        <span class="printer-stat-tier-label">${S.stats_total}</span>
                        <span class="printer-stat-counts">
                          <span class="printer-stat-success">${printer.remote_success_count}</span>
                          <span class="printer-stat-failed">${printer.remote_failed_count}</span>
                        </span>
                      </span>
                      <span class="printer-stat-tier">
                        <span class="printer-stat-tier-label">${S.stats_session}</span>
                        <span class="printer-stat-counts">
                          <span class="printer-stat-success">${printer.session_remote_success_count}</span>
                          <span class="printer-stat-failed">${printer.session_remote_failed_count}</span>
                        </span>
                      </span>
                    </span>
                  </div>
                </div>
              `
            )}
          </div>`;
    } else if (widget.widget_type === "server_status") {
      body = html`<${ServerStatusWidget} widget=${widget} servers=${servers} />`;
    } else if (widget.widget_type === "receipt_composer_items") {
      body = html`<${ReceiptComposerWidget} servers=${servers} />`;
    } else {
      body = html`<div id=${containerId} class="widget-plugin-mount"></div>`;
    }

    return html`
      <div
        class=${[
          "card",
          "widget-card",
          isDragging ? "widget-card-dragging" : "",
          hasAlert ? "widget-server-alert" : "",
          dropPosition === "before" ? "dnd-drop-before" : "",
          dropPosition === "after" ? "dnd-drop-after" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        onDragOver=${onDragOverCard}
        onDrop=${(event) => {
          event.preventDefault();
          event.stopPropagation();
          onDropOn();
        }}
      >
        <div class="widget-card-header">
          <span
            class="widget-drag-handle"
            draggable="true"
            title=${S.drag_to_reorder}
            onDragStart=${(event) => {
              event.dataTransfer.effectAllowed = "move";
              onDragStart();
            }}
            onDragEnd=${onDragEnd}
          >⋮⋮</span>
          <div class="dnd-move-buttons">
            <button type="button" class="dnd-move-btn" title=${S.receipt_move_up} disabled=${!canMoveUp} onClick=${onMoveUp}>▲</button>
            <button type="button" class="dnd-move-btn" title=${S.receipt_move_down} disabled=${!canMoveDown} onClick=${onMoveDown}>▼</button>
          </div>
          <h4>${widget.title}</h4>
          ${widget.widget_type === "server_status" || widget.widget_type === "printer_stats"
            ? html`<button class="widget-config-btn" title=${S.configure_widget} onClick=${onConfigure}>⚙</button>`
            : null}
          <button class="widget-remove-btn" title=${S.remove_widget} onClick=${onRemove}>×</button>
        </div>
        <div class="widget-card-body">${body}</div>
      </div>
    `;
  }

  function WidgetPicker({ catalog, onPick, onClose }) {
    const [activeTab, setActiveTab] = useState(WIDGET_ALL_TAB);
    const [search, setSearch] = useState("");

    const categoryLabel = (category) => category || S.plugin_category_unknown;
    const categories = Array.from(new Set(catalog.map((item) => item.category))).sort((a, b) =>
      categoryLabel(a).localeCompare(categoryLabel(b))
    );
    const countFor = (category) => catalog.filter((item) => item.category === category).length;

    const matchesSearch = (item) => {
      const query = search.trim().toLowerCase();
      return !query || item.title.toLowerCase().includes(query);
    };

    const groupsToRender = activeTab === WIDGET_ALL_TAB ? categories : [activeTab];
    const visibleItems = groupsToRender
      .flatMap((category) => catalog.filter((item) => item.category === category))
      .filter(matchesSearch);

    return html`
      <div class="modal-backdrop" role="presentation" onMouseDown=${(event) => {
        if (event.target === event.currentTarget) onClose();
      }}>
        <div class="widget-picker widget-picker-wide" role="dialog" aria-modal="true" aria-label=${S.add_widget}>
          <h3>${S.add_widget}</h3>
          <div class="category-layout">
            <nav class="category-tabs">
              <button
                class=${activeTab === WIDGET_ALL_TAB ? "category-tab active" : "category-tab"}
                onClick=${() => setActiveTab(WIDGET_ALL_TAB)}
              >
                <span>${S.widgets_all_tab}</span>
                <span class="category-tab-count">${catalog.length}</span>
              </button>
              ${categories.map(
                (category) => html`
                  <button
                    class=${activeTab === category ? "category-tab active" : "category-tab"}
                    onClick=${() => setActiveTab(category)}
                    key=${category || "__uncategorized__"}
                  >
                    <span>${categoryLabel(category)}</span>
                    <span class="category-tab-count">${countFor(category)}</span>
                  </button>
                `
              )}
            </nav>
            <div class="category-content">
              <input
                type="text"
                class="category-search"
                placeholder=${S.widget_picker_search_placeholder}
                value=${search}
                onInput=${(event) => setSearch(event.target.value)}
              />
              <div class="widget-picker-list">
                ${visibleItems.length === 0
                  ? html`<p class="hint-text">${S.no_widgets_match_filter}</p>`
                  : visibleItems.map(
                      (item) => html`
                        <button class="ghost widget-picker-item" key=${item.type} onClick=${() => onPick(item.type)}>
                          ${item.title}
                          <span class=${item.source === "plugin" ? "badge" : "badge badge-active"}>
                            ${item.source === "plugin" ? S.renderer_third_party : S.plugin_core}
                          </span>
                        </button>
                      `
                    )}
              </div>
            </div>
          </div>
          <div class="utility-actions">
            <button onClick=${onClose}>${S.close}</button>
          </div>
        </div>
      </div>
    `;
  }

  function PrinterActivitySettings({ widget, onSave, onClose }) {
    const config = widget.config || {};
    const [usedOnly, setUsedOnly] = useState(!!config.used_only);

    return html`
      <div class="modal-backdrop" role="presentation" onMouseDown=${(event) => {
        if (event.target === event.currentTarget) onClose();
      }}>
        <div class="widget-picker" role="dialog" aria-modal="true" aria-label=${S.printer_activity_settings_title}>
          <h3>${S.printer_activity_settings_title}</h3>
          <label class="checkbox-row">
            <input type="checkbox" checked=${usedOnly} onChange=${(event) => setUsedOnly(event.target.checked)} />
            <span>${S.printer_activity_used_only}</span>
          </label>
          <div class="utility-actions">
            <button onClick=${onClose}>${S.cancel}</button>
            <button class="primary" onClick=${() => onSave({ used_only: usedOnly })}>${S.save}</button>
          </div>
        </div>
      </div>
    `;
  }

  function ServerStatusSettings({ widget, servers, onSave, onClose }) {
    const config = widget.config || {};
    const [selected, setSelected] = useState(new Set(Array.isArray(config.server_ids) ? config.server_ids : []));
    const [autoRotate, setAutoRotate] = useState(!!config.auto_rotate);

    const toggle = (id) => {
      setSelected((current) => {
        const next = new Set(current);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    };

    return html`
      <div class="modal-backdrop" role="presentation" onMouseDown=${(event) => {
        if (event.target === event.currentTarget) onClose();
      }}>
        <div class="widget-picker" role="dialog" aria-modal="true" aria-label=${S.server_status_settings_title}>
          <h3>${S.server_status_settings_title}</h3>
          <div class="field-label">${S.server_status_pick_servers}</div>
          <div class="widget-settings-list">
            ${servers.length === 0
              ? html`<div class="server-empty-copy">${S.no_servers}</div>`
              : servers.map(
                  (server) => html`
                    <label class="checkbox-row" key=${server.id}>
                      <input type="checkbox" checked=${selected.has(server.id)} onChange=${() => toggle(server.id)} />
                      <span>${server.name}</span>
                    </label>
                  `
                )}
          </div>
          <label class="checkbox-row">
            <input type="checkbox" checked=${autoRotate} onChange=${(event) => setAutoRotate(event.target.checked)} />
            <span>${S.server_status_auto_rotate}</span>
          </label>
          <div class="utility-actions">
            <button onClick=${onClose}>${S.cancel}</button>
            <button
              class="primary"
              onClick=${() => onSave({ server_ids: Array.from(selected), auto_rotate: autoRotate })}
            >${S.save}</button>
          </div>
        </div>
      </div>
    `;
  }

  function WidgetArea({ recentJobs, logs, errorDetails, printerDetails, servers }) {
    const [layout, setLayout] = useState(null);
    const [pageIndex, setPageIndex] = useState(0);
    const [showPicker, setShowPicker] = useState(false);
    const [draggingId, setDraggingId] = useState(null);
    const [dropTargetId, setDropTargetId] = useState(null);
    const [dropAfter, setDropAfter] = useState(false);
    const [configuringId, setConfiguringId] = useState(null);

    const refreshLayout = () => {
      callApi("get_dashboard_layout").then((result) => {
        if (result && result.ok) setLayout({ pages: result.pages, catalog: result.catalog });
      });
    };

    useEffect(() => {
      whenApiReady(refreshLayout);
    }, []);

    if (!layout) return html`<div class="card widget-area"></div>`;

    const pageCount = Math.max(1, layout.pages.length);
    const currentPage = Math.min(pageIndex, pageCount - 1);
    const widgets = layout.pages[currentPage] || [];

    const applyLayout = (result) => {
      if (result && result.ok) setLayout({ pages: result.pages, catalog: result.catalog });
    };
    const addWidget = (widgetType) => {
      callApi("add_dashboard_widget", widgetType).then((result) => {
        applyLayout(result);
        if (result && result.ok) setShowPicker(false);
      });
    };
    const removeWidget = (id) => callApi("remove_dashboard_widget", id).then(applyLayout);
    const clearDropTarget = () => {
      setDropTargetId(null);
      setDropAfter(false);
    };
    const finishDrop = () => {
      if (draggingId != null) {
        const targetPosition = resolveDropIndex(widgets, draggingId, dropTargetId, dropAfter);
        callApi("reorder_dashboard_widget", draggingId, currentPage, targetPosition).then(applyLayout);
      }
      setDraggingId(null);
      clearDropTarget();
    };
    const moveWidgetBy = (widgetId, delta) => {
      const index = widgets.findIndex((w) => w.id === widgetId);
      const neighborIndex = index + delta;
      if (index === -1 || neighborIndex < 0 || neighborIndex >= widgets.length) return;
      const targetPosition = resolveDropIndex(widgets, widgetId, widgets[neighborIndex].id, delta > 0);
      callApi("reorder_dashboard_widget", widgetId, currentPage, targetPosition).then(applyLayout);
    };
    const saveWidgetConfig = (id, config) =>
      callApi("update_dashboard_widget_config", id, config).then((result) => {
        applyLayout(result);
        setConfiguringId(null);
      });
    const configuringWidget = widgets.find((widget) => widget.id === configuringId) || null;

    return html`
      <div class="card widget-area">
        <div class="widget-area-header">
          <button class="ghost" onClick=${() => setShowPicker(true)}>${S.add_widget}</button>
          ${pageCount > 1
            ? html`
                <div class="widget-page-nav">
                  <button class="page-arrow" disabled=${currentPage === 0} onClick=${() => setPageIndex(currentPage - 1)}>‹</button>
                  <span class="page-summary">${S.page_summary.replace("{page}", currentPage + 1).replace("{pages}", pageCount)}</span>
                  <button class="page-arrow" disabled=${currentPage === pageCount - 1} onClick=${() => setPageIndex(currentPage + 1)}>›</button>
                </div>
              `
            : null}
        </div>
        <div
          class="widget-grid"
          onDragOver=${(event) => {
            event.preventDefault();
            if (draggingId != null) clearDropTarget();
          }}
          onDrop=${(event) => {
            event.preventDefault();
            finishDrop();
          }}
        >
          ${widgets.map(
            (widget, index) => html`
              <${WidgetCard}
                key=${widget.id}
                widget=${widget}
                recentJobs=${recentJobs}
                logs=${logs}
                errorDetails=${errorDetails}
                printerDetails=${printerDetails}
                servers=${servers}
                onRemove=${() => removeWidget(widget.id)}
                onConfigure=${() => setConfiguringId(widget.id)}
                isDragging=${draggingId === widget.id}
                dropPosition=${dropTargetId === widget.id ? (dropAfter ? "after" : "before") : null}
                canMoveUp=${index > 0}
                canMoveDown=${index < widgets.length - 1}
                onDragStart=${() => setDraggingId(widget.id)}
                onDragEnd=${() => {
                  setDraggingId(null);
                  clearDropTarget();
                }}
                onDragOverCard=${(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  if (draggingId == null) return;
                  const rect = event.currentTarget.getBoundingClientRect();
                  setDropTargetId(widget.id);
                  setDropAfter(event.clientY - rect.top > rect.height / 2);
                }}
                onDropOn=${finishDrop}
                onMoveUp=${() => moveWidgetBy(widget.id, -1)}
                onMoveDown=${() => moveWidgetBy(widget.id, 1)}
              />
            `
          )}
        </div>
        ${draggingId != null
          ? html`
              <div
                class=${"dnd-drop-end" + (dropTargetId === null ? " dnd-drop-end-active" : "")}
                onDragOver=${(event) => {
                  event.preventDefault();
                  setDropTargetId(null);
                  setDropAfter(false);
                }}
                onDrop=${(event) => {
                  event.preventDefault();
                  finishDrop();
                }}
              >
                ${S.drop_at_end}
              </div>
            `
          : null}
        ${showPicker
          ? html`<${WidgetPicker} catalog=${layout.catalog} onPick=${addWidget} onClose=${() => setShowPicker(false)} />`
          : null}
        ${configuringWidget && configuringWidget.widget_type === "server_status"
          ? html`<${ServerStatusSettings}
              widget=${configuringWidget}
              servers=${servers}
              onSave=${(config) => saveWidgetConfig(configuringWidget.id, config)}
              onClose=${() => setConfiguringId(null)}
            />`
          : null}
        ${configuringWidget && configuringWidget.widget_type === "printer_stats"
          ? html`<${PrinterActivitySettings}
              widget=${configuringWidget}
              onSave=${(config) => saveWidgetConfig(configuringWidget.id, config)}
              onClose=${() => setConfiguringId(null)}
            />`
          : null}
      </div>
    `;
  }

  function App() {
    const [state, setState] = useState(null);
    const [error, setError] = useState(null);
    const stateSignature = useRef("");
    const readyNotified = useRef(false);

    const applyResult = useCallback((result) => {
      if (!result) return;
      const nextSignature = JSON.stringify(result.state);
      if (nextSignature !== stateSignature.current) {
        stateSignature.current = nextSignature;
        setState(result.state);
        applyAppearance(result.state);
      }
      if (!result.ok && result.error) {
        setError(result.error);
        window.setTimeout(() => setError(null), 4000);
      }
    }, []);

    useEffect(() => {
      let cancelled = false;
      const poll = () => callApi("get_state").then((result) => {
        if (!cancelled) applyResult(result);
      });
      const boot = () => poll();
      whenApiReady(boot);
      const id = window.setInterval(poll, POLL_MS);
      return () => {
        cancelled = true;
        window.clearInterval(id);
      };
    }, [applyResult]);

    useEffect(() => {
      if (state && !readyNotified.current) {
        readyNotified.current = true;
        callApi("notify_gui_ready");
      }
    }, [state]);

    if (!state) {
      return html`<div class="loading">${S.loading}</div>`;
    }

    document.title = state.window_title;
    return html`
      <div class="app">
        <${Sidebar}
          state=${state}
          onPlugins=${() => callApi("open_plugins_window").then(applyResult)}
          onServers=${() => callApi("open_servers_window").then(applyResult)}
          onPrinters=${() => callApi("open_printers_window").then(applyResult)}
          onHistory=${() => callApi("open_history_window").then(applyResult)}
          onSettings=${() => callApi("open_settings_window").then(applyResult)}
          onAbout=${() => callApi("open_about_window").then(applyResult)}
          onQuit=${() => callApi("quit_application")}
        />
        <div class="content">
          <${StatusBar}
            state=${state}
            onStart=${() => callApi("start_workers").then(applyResult)}
            onStop=${() => callApi("stop_workers").then(applyResult)}
          />
          <${WidgetArea}
            recentJobs=${state.recent_jobs}
            logs=${state.logs}
            errorDetails=${state.error_details}
            printerDetails=${state.printer_details}
            servers=${state.servers}
          />
        </div>
        ${error ? html`<div class="toast">${error}</div>` : null}
      </div>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
})();
