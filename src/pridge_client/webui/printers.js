/*
 * SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.
 */

(() => {
  "use strict";

  const { useEffect, useState } = React;
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

  function Printers() {
    const [printers, setPrinters] = useState([]);
    const [setupPrinter, setSetupPrinter] = useState("");
    const [printerCapabilities, setPrinterCapabilities] = useState(null);
    const [printerProfile, setPrinterProfile] = useState({ mode: "system_driver", driver_settings: {} });
    const [platformSystem, setPlatformSystem] = useState("");
    const [profileBusy, setProfileBusy] = useState(false);
    const [profileError, setProfileError] = useState("");
    const [profileMessage, setProfileMessage] = useState("");

    const refreshPrinters = () => {
      callApi("get_state").then((result) => {
        if (!result) return;
        if (result.state.appearance) {
          document.documentElement.dataset.darkness = (result.state.appearance.darkness_grade || "Onyx").toLowerCase();
        }
        setPrinters(result.state.printer_details || []);
      });
    };

    useEffect(() => {
      whenApiReady(refreshPrinters);
    }, []);

    const openPrinterSetup = (printerName) => {
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
        setPlatformSystem(result.platform_system || "");
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

    const setSubmissionMethod = (event) => {
      const nextProfile = { ...printerProfile, submission_method: event.target.value };
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

    return html`
      <main class="utility-page">
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.printers}</h1><p>${S.printers_hint}</p></div>
        </div>
        <div class="utility-content">
          <section class="settings-section">
            ${printers.length === 0
              ? html`<p class="hint-text">${S.no_printers}</p>`
              : printers.map(
                  (printer) => html`
                    <div class="setting-row" key=${printer.name}>
                      <div class="setting-copy">
                        <strong>${printer.name}</strong>
                        ${printer.is_default ? html`<span class="badge badge-active">${S.default_printer}</span>` : null}
                      </div>
                      <button class="ghost" onClick=${() => openPrinterSetup(printer.name)}>${S.configure}</button>
                    </div>
                  `
                )}
          </section>
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

                              ${platformSystem && platformSystem !== "Windows"
                                ? html`
                                    <div class="field">
                                      <label class="field-label">${S.submission_method}</label>
                                      <select
                                        value=${printerProfile.submission_method || ""}
                                        onChange=${setSubmissionMethod}
                                        disabled=${profileBusy}
                                      >
                                        <option value="">${S.submission_method_automatic}</option>
                                        <option value="direct_pdf">${S.submission_method_direct_pdf}</option>
                                        <option value="pdfium">${S.submission_method_pdfium}</option>
                                      </select>
                                      <small>${S.submission_method_hint}</small>
                                    </div>
                                  `
                                : null}

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

        <div class="utility-actions">
          <span class="utility-footer-info">${S.printers_count.replace("{count}", printers.length)}</span>
          <button onClick=${() => callApi("close_utility_window", "printers")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${Printers} />`);
})();
