(() => {
  "use strict";

  const { useEffect, useState } = React;
  const html = htm.bind(React.createElement);
  const S = window.PrintBridgeStrings;
  const params = new URLSearchParams(window.location.search);
  const serverId = params.get("server_id") || "";
  const windowKey = params.get("window_key") || "";

  function emptyForm() {
    return {
      name: "",
      server_url: "",
      enabled: true,
      polling_interval_seconds: 5,
      heartbeat_interval_seconds: 30,
      token: "",
    };
  }

  function callApi(name, ...args) {
    if (!window.pywebview || !window.pywebview.api || !window.pywebview.api[name]) {
      return Promise.resolve(null);
    }
    return window.pywebview.api[name](...args);
  }

  function ServerEditor() {
    const [form, setForm] = useState(emptyForm());
    const [loaded, setLoaded] = useState(!serverId);
    const [hasToken, setHasToken] = useState(false);
    const [showToken, setShowToken] = useState(false);
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState("");
    const [error, setError] = useState("");

    useEffect(() => {
      const boot = () => callApi("get_state").then((result) => {
        if (!result) return;
        if (!serverId) {
          setLoaded(true);
          return;
        }
        const server = result.state.servers.find((item) => item.id === serverId);
        if (!server) {
          setError(S.server_not_found);
          setLoaded(true);
          return;
        }
        setForm({
          name: server.name,
          server_url: server.server_url,
          enabled: server.enabled,
          polling_interval_seconds: server.polling_interval_seconds,
          heartbeat_interval_seconds: server.heartbeat_interval_seconds,
          token: "",
        });
        setHasToken(server.has_token);
        setLoaded(true);
      });
      if (window.pywebview) boot();
      else window.addEventListener("pywebviewready", boot, { once: true });
    }, []);

    const setField = (key) => (event) => {
      const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
      setForm((current) => ({ ...current, [key]: value }));
    };

    const close = () => callApi("close_server_window", windowKey);
    const save = (event) => {
      event.preventDefault();
      setError("");
      setMessage("");
      if (!form.name.trim() || !form.server_url.trim()) {
        setError(S.server_required);
        return;
      }
      setBusy(true);
      const request = serverId
        ? callApi("update_server", serverId, form)
        : callApi("add_server", form);
      request.then((result) => {
        setBusy(false);
        if (!result) return;
        if (!result.ok) {
          setError(result.error || S.save_failed);
          return;
        }
        close();
      });
    };

    const testConnection = () => {
      setBusy(true);
      setError("");
      setMessage("");
      callApi("test_server_connection", serverId, form).then((result) => {
        setBusy(false);
        if (!result) return;
        if (result.ok) setMessage(result.message || S.connection_success);
        else setError(result.error || S.connection_failed);
      });
    };

    if (!loaded) return html`<div class="loading">${S.loading}</div>`;

    document.title = serverId ? S.edit_server : S.add_server;

    return html`
      <form class="server-editor" onSubmit=${save}>
        <div class="editor-header">
          <h1>${serverId ? S.edit_server : S.add_server}</h1>
          <p>${S.server_connections_hint}</p>
        </div>

        <div class="field">
          <label class="field-label">${S.server_name}</label>
          <input type="text" value=${form.name} onChange=${setField("name")} autoFocus=${true} />
        </div>
        <div class="field">
          <label class="field-label">${S.server_url}</label>
          <input type="text" placeholder="https://example.com" value=${form.server_url} onChange=${setField("server_url")} />
        </div>
        <label class="checkbox-row editor-checkbox">
          <input type="checkbox" checked=${form.enabled} onChange=${setField("enabled")} />
          ${S.enabled}
        </label>
        <div class="field">
          <label class="field-label">${S.client_token}</label>
          <input
            type=${showToken ? "text" : "password"}
            value=${form.token}
            placeholder=${hasToken ? S.token_saved_placeholder : S.token_missing_placeholder}
            onChange=${setField("token")}
          />
          <label class="checkbox-row compact-checkbox">
            <input type="checkbox" checked=${showToken} onChange=${(event) => setShowToken(event.target.checked)} />
            ${S.show_token}
          </label>
          <div class="field-hint">${S.client_token_hint}</div>
        </div>
        <div class="interval-grid">
          <div class="field">
            <label class="field-label">${S.polling_interval}</label>
            <div class="field-row">
              <input type="number" min="1" value=${form.polling_interval_seconds} onChange=${setField("polling_interval_seconds")} />
              <span class="seconds-label">${S.seconds}</span>
            </div>
          </div>
          <div class="field">
            <label class="field-label">${S.heartbeat_interval}</label>
            <div class="field-row">
              <input type="number" min="5" value=${form.heartbeat_interval_seconds} onChange=${setField("heartbeat_interval_seconds")} />
              <span class="seconds-label">${S.seconds}</span>
            </div>
          </div>
        </div>

        ${message ? html`<div class="connection-result success-result">${message}</div>` : null}
        ${error ? html`<div class="connection-result error-result">${error}</div>` : null}

        <div class="editor-actions">
          <button type="button" class="ghost" onClick=${testConnection} disabled=${busy}>
            ${busy ? S.testing : S.test_connection}
          </button>
          <div class="editor-actions-right">
            <button type="button" onClick=${close}>${S.cancel}</button>
            <button type="submit" class="primary" disabled=${busy}>${serverId ? S.update : S.add}</button>
          </div>
        </div>
      </form>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${ServerEditor} />`);
})();
