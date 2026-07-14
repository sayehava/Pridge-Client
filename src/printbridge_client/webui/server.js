/*
 * SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.
 */

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
    const [setupPrinter, setSetupPrinter] = useState("");
    const [printerCapabilities, setPrinterCapabilities] = useState(null);
    const [printerProfile, setPrinterProfile] = useState({ mode: "system_driver", driver_settings: {} });
    const [profileBusy, setProfileBusy] = useState(false);
    const [profileError, setProfileError] = useState("");
    const [profileMessage, setProfileMessage] = useState("");

    useEffect(() => {
      const boot = () => callApi("get_state").then((result) => {
        if (!result) return;
        if (result.state.appearance) {
          document.documentElement.dataset.darkness = (result.state.appearance.darkness_grade || "Onyx").toLowerCase();
        }
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

    const openPrinterSetup = (printerName) => {
      if (!printerName) return;
      setSetupPrinter(printerName);
      setPrinterCapabilities(null);
      setPrinterProfile({ mode: "system_driver", driver_settings: {} });
      setProfileError("");
      setProfileMessage("");
      setProfileBusy(true);
      callApi("get_printer_capabilities", printerName).then((result) => {
        setProfileBusy(false);
        if (!result) return;
        if (!result.ok) {
          setProfileError(result.error || S.driver_capabilities_failed);
          return;
        }
        setPrinterCapabilities(result.capabilities || null);
        setPrinterProfile(result.profile || { mode: "system_driver", driver_settings: {} });
      });
    };

    const closePrinterSetup = () => {
      if (profileBusy) return;
      setSetupPrinter("");
      setPrinterCapabilities(null);
      setProfileError("");
      setProfileMessage("");
    };

    const persistPrinterProfile = (nextProfile) => {
      setProfileBusy(true);
      setProfileError("");
      setProfileMessage("");
      callApi("update_printer_profile", setupPrinter, nextProfile).then((result) => {
        setProfileBusy(false);
        if (!result) return;
        if (!result.ok) {
          setProfileError(result.error || S.printer_profile_save_failed);
          return;
        }
        setPrinterProfile(result.profile || nextProfile);
        setPrinterCapabilities(result.capabilities || printerCapabilities);
        setProfileMessage(S.settings_saved_automatically);
      });
    };

    const setPrintingMode = (event) => {
      const nextProfile = { ...printerProfile, mode: event.target.value };
      setPrinterProfile(nextProfile);
      persistPrinterProfile(nextProfile);
    };

    const setDriverOption = (optionId, valueId) => {
      const nextProfile = {
        ...printerProfile,
        driver_settings: { ...(printerProfile.driver_settings || {}), [optionId]: valueId },
      };
      setPrinterProfile(nextProfile);
      persistPrinterProfile(nextProfile);
    };

    const openNativeDriverSettings = () => {
      setProfileBusy(true);
      setProfileError("");
      setProfileMessage("");
      callApi("open_printer_driver_settings", setupPrinter).then((result) => {
        setProfileBusy(false);
        if (!result) return;
        if (!result.ok) {
          setProfileError(result.error || S.native_driver_settings_failed);
          return;
        }
        setPrinterCapabilities(result.capabilities || printerCapabilities);
        setPrinterProfile(result.profile || printerProfile);
        setProfileMessage(S.driver_settings_updated);
      });
    };

    const testPrinter = () => {
      setProfileBusy(true);
      setProfileError("");
      setProfileMessage("");
      callApi("test_printer", setupPrinter).then((result) => {
        setProfileBusy(false);
        if (!result) return;
        if (!result.ok) {
          setProfileError(result.error || S.test_print_failed);
          return;
        }
        setProfileMessage(result.message || S.test_print_submitted);
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
                    >
                      <div class="mapping-endpoint">
                        <div class="mapping-endpoint-name">${mapping.remote_printer_name}</div>
                        <div class="mapping-endpoint-meta">
                          <span>ID ${mapping.remote_printer_id}</span>
                          ${remote && !remote.enabled ? html`<span class="remote-disabled">${S.server_endpoint_disabled}</span>` : null}
                        </div>
                      </div>
                      <div class="mapping-local">
                        <div class="mapping-local-controls">
                          <select
                            aria-label=${S.local_printer}
                            value=${mapping.local_printer_name}
                            onChange=${(event) => mapEndpoint(mapping.remote_printer_id, event.target.value)}
                          >
                            <option value="">${S.mapping_disabled}</option>
                            ${printers.map((name) => html`<option value=${name} key=${name}>${name}</option>`)}
                          </select>
                          <button
                            type="button"
                            class="ghost printer-configure-button"
                            disabled=${!mapping.local_printer_name}
                            onClick=${() => openPrinterSetup(mapping.local_printer_name)}
                          >
                            ${S.configure}
                          </button>
                        </div>
                      </div>
                    </div>
                  `;
                  }
                )}
              </div>`}
        </div>

        ${setupPrinter
          ? html`
              <div class="printer-setup-backdrop" role="presentation" onMouseDown=${closePrinterSetup}>
                <div
                  class="printer-setup-dialog"
                  role="dialog"
                  aria-modal="true"
                  aria-label=${S.printer_setup}
                  onMouseDown=${(event) => event.stopPropagation()}
                >
                  <div class="printer-setup-header">
                    <div>
                      <h2>${S.printer_setup}</h2>
                      <p>${setupPrinter}</p>
                    </div>
                  </div>

                  ${profileBusy && !printerCapabilities
                    ? html`<div class="driver-loading">${S.loading_driver_capabilities}</div>`
                    : html`
                        <div class="field">
                          <label class="field-label">${S.printing_mode}</label>
                          <select value=${printerProfile.mode} onChange=${setPrintingMode} disabled=${profileBusy}>
                            <option value="raw">${S.raw_mode}</option>
                            <option
                              value="system_driver"
                              disabled=${printerCapabilities && !printerCapabilities.system_driver_available}
                            >
                              ${S.system_driver_mode}
                            </option>
                          </select>
                        </div>

                        ${printerProfile.mode === "raw"
                          ? html`<div class="driver-mode-note">${S.raw_mode_hint}</div>`
                          : printerCapabilities && !printerCapabilities.system_driver_available
                          ? html`<div class="connection-result error-result">${S.system_driver_unavailable}</div>`
                          : html`
                              <div class="driver-mode-note">
                                ${S.system_driver_mode_hint}
                                ${printerCapabilities && printerCapabilities.driver_name
                                  ? html`<strong>${printerCapabilities.driver_name}</strong>`
                                  : null}
                              </div>

                              ${printerCapabilities && printerCapabilities.supports_native_dialog
                                ? html`
                                    <div class="native-driver-row">
                                      <div>
                                        <strong>${S.native_driver_settings}</strong>
                                        <small>${S.native_driver_settings_hint}</small>
                                      </div>
                                      <button type="button" class="ghost" onClick=${openNativeDriverSettings} disabled=${profileBusy}>
                                        ${S.open_driver_settings}
                                      </button>
                                    </div>
                                  `
                                : null}

                              ${printerCapabilities && printerCapabilities.options.length
                                ? html`
                                    <div class="driver-options">
                                      ${printerCapabilities.options.map(
                                        (option) => html`
                                          <div class="field driver-option" key=${option.id}>
                                            <label class="field-label">${option.label}</label>
                                            <select
                                              value=${printerProfile.driver_settings[option.id] || option.default}
                                              onChange=${(event) => setDriverOption(option.id, event.target.value)}
                                              disabled=${profileBusy}
                                            >
                                              ${option.choices.map(
                                                (choice) => html`<option value=${choice.id} key=${choice.id}>${choice.label}</option>`
                                              )}
                                            </select>
                                          </div>
                                        `
                                      )}
                                    </div>
                                  `
                                : printerCapabilities && !printerCapabilities.supports_native_dialog
                                ? html`<div class="driver-mode-note">${S.no_driver_options}</div>`
                                : null}
                            `}
                      `}

                  ${profileMessage ? html`<div class="connection-result success-result">${profileMessage}</div>` : null}
                  ${profileError ? html`<div class="connection-result error-result">${profileError}</div>` : null}

                  <div class="printer-setup-actions">
                    <button
                      type="button"
                      class="ghost"
                      onClick=${testPrinter}
                      disabled=${profileBusy || !printerCapabilities || printerProfile.mode !== "system_driver"}
                      title=${printerProfile.mode === "system_driver" ? S.test_print : S.test_print_driver_only}
                    >
                      ${profileBusy ? S.working : S.test_print}
                    </button>
                    <button type="button" class="primary" onClick=${closePrinterSetup} disabled=${profileBusy}>${S.done}</button>
                  </div>
                </div>
              </div>
            `
          : null}

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
