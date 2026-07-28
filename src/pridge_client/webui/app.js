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

  function Sidebar({ state, onPlugins, onServers, onPrinters, onSettings, onAbout, onQuit }) {
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

  function WidgetCard({
    widget,
    recentJobs,
    logs,
    printerDetails,
    servers,
    onRemove,
    onConfigure,
    isDragging,
    dropPosition,
    onDragStart,
    onDragEnd,
    onDragOverCard,
    onDropOn,
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
                    <span class="printer-stat-counts">
                      <span class="printer-stat-success">${printer.test_success_count}</span>
                      <span class="printer-stat-failed">${printer.test_failed_count}</span>
                    </span>
                  </div>
                  <div class="printer-stat-row">
                    <span class="printer-stat-label">${S.remote_prints}</span>
                    <span class="printer-stat-counts">
                      <span class="printer-stat-success">${printer.remote_success_count}</span>
                      <span class="printer-stat-failed">${printer.remote_failed_count}</span>
                    </span>
                  </div>
                </div>
              `
            )}
          </div>`;
    } else if (widget.widget_type === "server_status") {
      body = html`<${ServerStatusWidget} widget=${widget} servers=${servers} />`;
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
    return html`
      <div class="modal-backdrop" role="presentation" onMouseDown=${(event) => {
        if (event.target === event.currentTarget) onClose();
      }}>
        <div class="widget-picker" role="dialog" aria-modal="true" aria-label=${S.add_widget}>
          <h3>${S.add_widget}</h3>
          <div class="widget-picker-list">
            ${catalog.map(
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

  function WidgetArea({ recentJobs, logs, printerDetails, servers }) {
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
            (widget) => html`
              <${WidgetCard}
                key=${widget.id}
                widget=${widget}
                recentJobs=${recentJobs}
                logs=${logs}
                printerDetails=${printerDetails}
                servers=${servers}
                onRemove=${() => removeWidget(widget.id)}
                onConfigure=${() => setConfiguringId(widget.id)}
                isDragging=${draggingId === widget.id}
                dropPosition=${dropTargetId === widget.id ? (dropAfter ? "after" : "before") : null}
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
