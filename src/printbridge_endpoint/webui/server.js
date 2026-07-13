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
      default_printer: "",
      printer_mappings: [],
      token: "",
    };
  }

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

  function ServerEditor() {
    const [form, setForm] = useState(emptyForm());
    const [loaded, setLoaded] = useState(!serverId);
    const [hasToken, setHasToken] = useState(false);
    const [showToken, setShowToken] = useState(false);
    const [busy, setBusy] = useState(false);
    const [discovering, setDiscovering] = useState(false);
    const [printers, setPrinters] = useState([]);
    const [remotePrinters, setRemotePrinters] = useState([]);
    const [message, setMessage] = useState("");
    const [error, setError] = useState("");

    useEffect(() => {
      const boot = () => callApi("get_state").then((result) => {
        if (!result) return;
        setPrinters(result.state.printers || []);
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
        const serverForm = {
          name: server.name,
          server_url: server.server_url,
          enabled: server.enabled,
          polling_interval_seconds: server.polling_interval_seconds,
          heartbeat_interval_seconds: server.heartbeat_interval_seconds,
          default_printer: "",
          printer_mappings: server.printer_mappings || [],
          token: "",
        };
        setForm(serverForm);
        setRemotePrinters(
          (server.printer_mappings || []).map((mapping) => ({
            remote_printer_id: mapping.remote_printer_id,
            remote_printer_name: mapping.remote_printer_name,
            enabled: true,
          }))
        );
        setHasToken(server.has_token);
        setLoaded(true);
        discoverRemotePrinters(serverForm);
      });
      whenApiReady(boot);
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
        if (result.ok) {
          setMessage(result.message || S.connection_success);
          discoverRemotePrinters(form);
        } else setError(result.error || S.connection_failed);
      });
    };

    const discoverRemotePrinters = (settings = form) => {
      setDiscovering(true);
      setError("");
      callApi("discover_remote_printers", serverId, settings).then((result) => {
        setDiscovering(false);
        if (!result) return;
        if (!result.ok) {
          setError(result.error || S.connection_failed);
          return;
        }
        const discovered = result.remote_printers || [];
        setRemotePrinters(discovered);
        setForm((current) => ({
          ...current,
          default_printer: "",
          printer_mappings: discovered.map((printer) => {
            const existing = current.printer_mappings.find(
              (mapping) => mapping.remote_printer_id === printer.remote_printer_id
            );
            return {
              remote_printer_id: printer.remote_printer_id,
              remote_printer_name: printer.remote_printer_name,
              local_printer_name: existing ? existing.local_printer_name : "",
            };
          }),
        }));
        setMessage(discovered.length ? S.remote_printers_found.replace("{count}", discovered.length) : S.no_remote_printers);
      });
    };

    const mapEndpoint = (remotePrinterId, localPrinterName) => {
      setForm((current) => ({
        ...current,
        printer_mappings: current.printer_mappings.map((mapping) =>
          mapping.remote_printer_id === remotePrinterId ? { ...mapping, local_printer_name: localPrinterName } : mapping
        ),
      }));
    };

    const dropPrinter = (event, remotePrinterId) => {
      event.preventDefault();
      const printerName = event.dataTransfer.getData("text/plain");
      if (printerName) mapEndpoint(remotePrinterId, printerName);
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
          <span><strong>${S.enabled}</strong><small>${S.automatic_server_hint}</small></span>
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

        <div class="editor-section">
          <div class="section-heading-row">
            <div>
              <h2>${S.printer_mappings}</h2>
              <p>${S.printer_mappings_hint}</p>
            </div>
            <div class="button-row section-actions">
              <button type="button" class="ghost" onClick=${() => discoverRemotePrinters(form)} disabled=${discovering || busy}>
                ${discovering ? S.discovering : S.refresh_endpoints}
              </button>
            </div>
          </div>

          <div class="local-printer-pool">
            <div class="pool-heading">
              <span>${S.local_printers}</span>
              <small>${S.drag_printer_hint}</small>
            </div>
            <div class="printer-chips">
              ${printers.length === 0
                ? html`<span class="printer-pool-empty">${S.no_printers}</span>`
                : printers.map(
                    (name) => html`<button
                      type="button"
                      class="printer-chip"
                      draggable="true"
                      onDragStart=${(event) => event.dataTransfer.setData("text/plain", name)}
                      key=${name}
                    >${name}</button>`
                  )}
            </div>
          </div>

          ${discovering && form.printer_mappings.length === 0
            ? html`<div class="mapping-empty">${S.discovering}</div>`
            : form.printer_mappings.length === 0
            ? html`<div class="mapping-empty">${S.no_mappings}</div>`
            : html`<div class="mapping-list">
                ${form.printer_mappings.map(
                  (mapping) => {
                    const remote = remotePrinters.find(
                      (printer) => printer.remote_printer_id === mapping.remote_printer_id
                    );
                    return html`
                    <div
                      class=${mapping.local_printer_name ? "mapping-row mapping-active" : "mapping-row"}
                      key=${mapping.remote_printer_id}
                      onDragOver=${(event) => event.preventDefault()}
                      onDrop=${(event) => dropPrinter(event, mapping.remote_printer_id)}
                    >
                      <div class="mapping-endpoint">
                        <div class="mapping-endpoint-name">${mapping.remote_printer_name}</div>
                        <div class="mapping-endpoint-meta">
                          <span>ID ${mapping.remote_printer_id}</span>
                          ${remote && !remote.enabled ? html`<span class="remote-disabled">${S.server_endpoint_disabled}</span>` : null}
                        </div>
                      </div>
                      <div class="mapping-local">
                        <label class="field-label">${S.local_printer}</label>
                        <select
                          value=${mapping.local_printer_name}
                          onChange=${(event) => mapEndpoint(mapping.remote_printer_id, event.target.value)}
                        >
                          <option value="">${S.mapping_disabled}</option>
                          ${printers.map((name) => html`<option value=${name} key=${name}>${name}</option>`)}
                        </select>
                      </div>
                    </div>
                  `;
                  }
                )}
              </div>`}
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
