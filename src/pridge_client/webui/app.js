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

  function WidgetCard({ widget, index, widgetCount, pageIndex, pageCount, recentJobs, logs, onRemove, onMove }) {
    const containerId = `pridge-widget-${widget.id}`;
    const scriptLoaded = useRef(false);

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
    } else {
      body = html`<div id=${containerId} class="widget-plugin-mount"></div>`;
    }

    return html`
      <div class="card widget-card">
        <div class="widget-card-header">
          <h4>${widget.title}</h4>
          <div class="widget-card-actions">
            <button class="widget-move-btn" title=${S.move_left} disabled=${pageIndex === 0 && index === 0} onClick=${() => onMove("left")}>◀</button>
            <button class="widget-move-btn" title=${S.move_up} disabled=${index === 0} onClick=${() => onMove("up")}>▲</button>
            <button class="widget-move-btn" title=${S.move_down} disabled=${index === widgetCount - 1} onClick=${() => onMove("down")}>▼</button>
            <button class="widget-move-btn" title=${S.move_right} onClick=${() => onMove("right")}>▶</button>
            <button class="widget-remove-btn" title=${S.remove_widget} onClick=${onRemove}>×</button>
          </div>
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
                    ${item.source === "plugin" ? S.renderer_third_party : S.renderer_builtin}
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

  function WidgetArea({ recentJobs, logs }) {
    const [layout, setLayout] = useState(null);
    const [pageIndex, setPageIndex] = useState(0);
    const [showPicker, setShowPicker] = useState(false);

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
    const moveWidget = (id, direction) => callApi("move_dashboard_widget", id, direction).then(applyLayout);

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
        <div class="widget-grid">
          ${widgets.map(
            (widget, index) => html`
              <${WidgetCard}
                key=${widget.id}
                widget=${widget}
                index=${index}
                widgetCount=${widgets.length}
                pageIndex=${currentPage}
                pageCount=${pageCount}
                recentJobs=${recentJobs}
                logs=${logs}
                onRemove=${() => removeWidget(widget.id)}
                onMove=${(direction) => moveWidget(widget.id, direction)}
              />
            `
          )}
        </div>
        ${showPicker
          ? html`<${WidgetPicker} catalog=${layout.catalog} onPick=${addWidget} onClose=${() => setShowPicker(false)} />`
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
          <${WidgetArea} recentJobs=${state.recent_jobs} logs=${state.logs} />
        </div>
        ${error ? html`<div class="toast">${error}</div>` : null}
      </div>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
})();
