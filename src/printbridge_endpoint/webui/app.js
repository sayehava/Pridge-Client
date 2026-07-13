(() => {
  "use strict";

  const { useState, useEffect, useCallback, useRef } = React;
  const html = htm.bind(React.createElement);
  const S = window.PrintBridgeStrings;
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

  function ConfirmDialog({ server, onCancel, onConfirm }) {
    useEffect(() => {
      const closeOnEscape = (event) => {
        if (event.key === "Escape") onCancel();
      };
      window.addEventListener("keydown", closeOnEscape);
      return () => window.removeEventListener("keydown", closeOnEscape);
    }, [onCancel]);

    if (!server) return null;

    return html`
      <div class="modal-backdrop" role="presentation" onMouseDown=${(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}>
        <div class="confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message">
          <img class="confirm-app-icon" src="assets/Icon.png" alt="" />
          <div class="confirm-copy">
            <h2 id="confirm-title">${S.remove_server_title}</h2>
            <p id="confirm-message">${S.confirm_remove.replace("{name}", server.name)}</p>
          </div>
          <div class="confirm-actions">
            <button autoFocus=${true} onClick=${onCancel}>${S.cancel}</button>
            <button class="danger" onClick=${onConfirm}>${S.remove}</button>
          </div>
        </div>
      </div>
    `;
  }

  function Sidebar({ state, onSettings, onAbout, onQuit }) {
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
          <button class="sidebar-nav full-width" onClick=${onSettings}><span aria-hidden="true">⚙</span>${S.settings}</button>
          <button class="sidebar-nav full-width" onClick=${onAbout}><span aria-hidden="true">ⓘ</span>${S.about}</button>
          <button class="danger full-width" onClick=${onQuit}>${S.quit}</button>
        </div>
      </div>
    `;
  }

  function ServerConnections({ servers, onAdd, onEdit, onRemove, onStart, onStop }) {
    const [page, setPage] = useState(0);
    const [direction, setDirection] = useState("forward");
    const previousServerCount = useRef(servers.length);
    const pageCount = Math.max(1, servers.length);
    const currentPage = Math.min(page, pageCount - 1);

    useEffect(() => {
      if (servers.length > previousServerCount.current) {
        setDirection("forward");
        setPage(servers.length - 1);
      } else {
        setPage((current) => Math.min(current, pageCount - 1));
      }
      previousServerCount.current = servers.length;
    }, [servers.length, pageCount]);

    const goToPage = (nextPage) => {
      const bounded = Math.min(Math.max(nextPage, 0), pageCount - 1);
      if (bounded === currentPage) return;
      setDirection(bounded > currentPage ? "forward" : "backward");
      setPage(bounded);
    };
    const pageServers = servers.length > 0 ? [servers[currentPage]] : [];
    const visiblePages = Array.from(new Set([0, currentPage - 1, currentPage, currentPage + 1, pageCount - 1]))
      .filter((item) => item >= 0 && item < pageCount)
      .sort((a, b) => a - b);
    const paginationItems = [];
    visiblePages.forEach((item, index) => {
      if (index > 0 && item - visiblePages[index - 1] > 1) paginationItems.push(`gap-${item}`);
      paginationItems.push(item);
    });

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
              <div class=${`server-page page-slide-${direction}`} key=${currentPage}>
              ${pageServers.map(
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
              </div>
            </div>`}
        ${servers.length > 0 && pageCount > 1
          ? html`<nav class="server-pagination" aria-label=${S.server_pages}>
              <button class="page-arrow" aria-label=${S.previous_page} disabled=${currentPage === 0} onClick=${() => goToPage(currentPage - 1)}>‹</button>
              <div class="page-numbers">
                ${paginationItems.map((item) =>
                  typeof item === "string"
                    ? html`<span class="page-gap" key=${item}>…</span>`
                    : html`<button
                        class=${item === currentPage ? "page-number active" : "page-number"}
                        aria-label=${S.page_number.replace("{page}", item + 1)}
                        aria-current=${item === currentPage ? "page" : null}
                        onClick=${() => goToPage(item)}
                        key=${item}
                      >${item + 1}</button>`
                )}
              </div>
              <span class="page-summary">${S.page_summary.replace("{page}", currentPage + 1).replace("{pages}", pageCount)}</span>
              <button class="page-arrow" aria-label=${S.next_page} disabled=${currentPage === pageCount - 1} onClick=${() => goToPage(currentPage + 1)}>›</button>
            </nav>`
          : null}
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
    const [serverToRemove, setServerToRemove] = useState(null);
    const stateSignature = useRef("");

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

    if (!state) {
      return html`<div class="loading">${S.loading}</div>`;
    }

    document.title = state.window_title;
    const onAdd = () => callApi("open_server_window", "").then(applyResult);
    const onEdit = (serverId) => callApi("open_server_window", serverId).then(applyResult);
    const onRemove = (server) => setServerToRemove(server);
    const confirmRemove = () => {
      if (!serverToRemove) return;
      callApi("remove_server", serverToRemove.id).then(applyResult);
      setServerToRemove(null);
    };
    return html`
      <div class="app">
        <${Sidebar}
          state=${state}
          onSettings=${() => callApi("open_settings_window").then(applyResult)}
          onAbout=${() => callApi("open_about_window").then(applyResult)}
          onQuit=${() => callApi("quit_application")}
        />
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
            onStart=${() => callApi("start_workers").then(applyResult)}
            onStop=${() => callApi("stop_workers").then(applyResult)}
          />
          <${JobsCard} jobs=${state.recent_jobs} />
          <${LogsCard} logs=${state.logs} />
        </div>
        <${ConfirmDialog}
          server=${serverToRemove}
          onCancel=${() => setServerToRemove(null)}
          onConfirm=${confirmRemove}
        />
        ${error ? html`<div class="toast">${error}</div>` : null}
      </div>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${App} />`);
})();
