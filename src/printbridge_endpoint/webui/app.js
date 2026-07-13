(() => {
  "use strict";

  const { useState, useEffect, useCallback, useRef } = React;
  const html = htm.bind(React.createElement);
  const S = window.PrintBridgeStrings;
  const POLL_MS = 1000;

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

  function Badge({ text, active = false }) {
    return html`<span class=${active ? "badge badge-active" : "badge"}>${text}</span>`;
  }

  function Sidebar({ state, onQuit }) {
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
          <button class="danger full-width" onClick=${onQuit}>${S.quit}</button>
        </div>
      </div>
    `;
  }

  function ServerConnections({ servers, onAdd, onEdit, onRemove, onStart, onStop }) {
    return html`
      <div class="card area-server">
        <div class="card-heading-row">
          <div>
            <h3 class="card-title">${S.server_connections}</h3>
            <div class="card-subtitle">${S.server_connections_hint}</div>
          </div>
          <button class="primary" onClick=${onAdd}>${S.add_server}</button>
        </div>

        ${servers.length === 0
          ? html`<div class="server-empty">
              <div class="server-empty-title">${S.no_servers}</div>
              <div class="server-empty-copy">${S.no_servers_hint}</div>
            </div>`
          : html`<div class="server-list">
              ${servers.map(
                (server) => html`
                  <div class="server-item" key=${server.id}>
                    <div class="server-item-main">
                      <div class="server-item-heading">
                        <span class="server-name">${server.name}</span>
                        <${Badge} text=${server.status} active=${server.running} />
                      </div>
                      <div class="server-url">${server.server_url}</div>
                      <div class="server-meta">
                        <span>${server.enabled ? S.enabled : S.disabled}</span>
                        <span>${server.has_token ? S.token_saved : S.token_missing}</span>
                        <span>${server.polling_interval_seconds}s ${S.polling_short}</span>
                        <span>${server.heartbeat_interval_seconds}s ${S.heartbeat_short}</span>
                        <span>${server.printer_mappings.length} ${S.mappings_short}</span>
                      </div>
                    </div>
                    <div class="server-actions">
                      ${server.running
                        ? html`<button class="danger" onClick=${() => onStop(server.id)}>${S.stop}</button>`
                        : html`<button class="success" onClick=${() => onStart(server.id)}>${S.start}</button>`}
                      <button class="ghost" onClick=${() => onEdit(server.id)}>${S.edit}</button>
                      <button class="ghost danger-text" onClick=${() => onRemove(server)}>${S.remove}</button>
                    </div>
                  </div>
                `
              )}
            </div>`}
      </div>
    `;
  }

  function ControlsCard({ state, onChangeSetting, onSave, onStart, onStop }) {
    return html`
      <div class="card area-polling">
        <h3 class="card-title">${S.endpoint_controls}</h3>
        <label class="checkbox-row">
          <input
            type="checkbox"
            checked=${state.start_polling_on_launch}
            onChange=${(event) => onChangeSetting("set_start_polling_on_launch", event.target.checked)}
          />
          ${S.start_polling_on_launch}
        </label>
        <label class="checkbox-row">
          <input
            type="checkbox"
            checked=${state.start_at_login}
            onChange=${(event) => onChangeSetting("set_start_at_login", event.target.checked)}
          />
          ${S.start_at_login}
        </label>
        <div class="badge-row">
          <label class="field-label">${S.connection_status}</label>
          <${Badge} text=${state.connection_status} />
        </div>
        <div class="badge-row">
          <label class="field-label">${S.heartbeat}</label>
          <${Badge} text=${state.heartbeat_status} />
        </div>
        <div class="button-row controls-actions">
          <button class="primary" onClick=${onSave}>${S.save}</button>
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

    const applyResult = useCallback((result) => {
      if (!result) return;
      setState(result.state);
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

    if (!state) {
      return html`<div class="loading">${S.loading}</div>`;
    }

    document.title = state.window_title;
    const onAdd = () => callApi("open_server_window", "").then(applyResult);
    const onEdit = (serverId) => callApi("open_server_window", serverId).then(applyResult);
    const onRemove = (server) => {
      if (window.confirm(S.confirm_remove.replace("{name}", server.name))) {
        callApi("remove_server", server.id).then(applyResult);
      }
    };
    const onChangeSetting = (method, value) => callApi(method, value).then(applyResult);

    return html`
      <div class="app">
        <${Sidebar} state=${state} onQuit=${() => callApi("quit_application")} />
        <div class="content">
          <${ServerConnections}
            servers=${state.servers}
            onAdd=${onAdd}
            onEdit=${onEdit}
            onRemove=${onRemove}
            onStart=${(serverId) => callApi("start_server", serverId).then(applyResult)}
            onStop=${(serverId) => callApi("stop_server", serverId).then(applyResult)}
          />
          <${ControlsCard}
            state=${state}
            onChangeSetting=${onChangeSetting}
            onSave=${() => callApi("save_settings").then(applyResult)}
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
