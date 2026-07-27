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

  function Sidebar({ state, onPlugins, onServers, onSettings, onAbout, onQuit }) {
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
          <button class="sidebar-nav full-width" onClick=${onSettings}><span aria-hidden="true">⚙</span>${S.settings}</button>
          <button class="sidebar-nav full-width" onClick=${onAbout}><span aria-hidden="true">ⓘ</span>${S.about}</button>
          <button class="danger full-width" onClick=${onQuit}>${S.quit}</button>
        </div>
      </div>
    `;
  }

  function ServersSummaryCard({ servers, onManage }) {
    const running = servers.filter((server) => server.running).length;
    return html`
      <div class="card area-server">
        <div class="card-heading-row">
          <div>
            <h3 class="card-title">${S.server_connections}</h3>
            <div class="card-subtitle">${S.servers_summary
              .replace("{running}", running)
              .replace("{total}", servers.length)}</div>
          </div>
          <button class="primary" onClick=${onManage}>${S.manage_servers}</button>
        </div>
      </div>
    `;
  }

  function ControlsCard({ state, onStart, onStop }) {
    return html`
      <div class="card area-polling">
        <h3 class="card-title">${S.endpoint_controls}</h3>
        <div class="card-subtitle controls-hint">${S.endpoint_controls_hint}</div>
        <div class="badge-row">
          <label class="field-label">${S.connection_status}</label>
          <${Badge} text=${state.connection_status} />
        </div>
        <div class="badge-row">
          <label class="field-label">${S.heartbeat}</label>
          <${Badge} text=${state.heartbeat_status} />
        </div>
        <div class="button-row controls-actions">
          <button class="success" onClick=${onStart}>${S.start_all}</button>
          <button class="danger" onClick=${onStop}>${S.stop_all}</button>
        </div>
      </div>
    `;
  }

  function JobsCard({ jobs }) {
    return html`
      <div class="card area-jobs">
        <h3 class="card-title">${S.recent_jobs}</h3>
        ${jobs.length === 0
          ? html`<div class="scroll-panel empty">${S.no_jobs}</div>`
          : html`<div class="scroll-panel">
              ${jobs.map((line, index) => html`<div class="job-line" key=${index}>${line}</div>`)}
            </div>`}
      </div>
    `;
  }

  function LogsCard({ logs }) {
    const panelRef = useRef(null);
    useEffect(() => {
      const element = panelRef.current;
      if (element) element.scrollTop = element.scrollHeight;
    }, [logs]);

    return html`
      <div class="card area-logs">
        <h3 class="card-title">${S.logs_status}</h3>
        ${logs.length === 0
          ? html`<div class="scroll-panel empty">${S.no_logs}</div>`
          : html`<div class="scroll-panel" ref=${panelRef}>
              ${logs.map((line, index) => html`<div class="log-line" key=${index}>${line}</div>`)}
            </div>`}
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
          onSettings=${() => callApi("open_settings_window").then(applyResult)}
          onAbout=${() => callApi("open_about_window").then(applyResult)}
          onQuit=${() => callApi("quit_application")}
        />
        <div class="content">
          <${ServersSummaryCard}
            servers=${state.servers}
            onManage=${() => callApi("open_servers_window").then(applyResult)}
          />
          <${ControlsCard}
            state=${state}
            onStart=${() => callApi("start_workers").then(applyResult)}
            onStop=${() => callApi("stop_workers").then(applyResult)}
          />
          <${JobsCard} jobs=${state.recent_jobs} />
          <${LogsCard} logs=${state.logs} />
        </div>
        ${error ? html`<div class="toast">${error}</div>` : null}
      </div>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
})();
