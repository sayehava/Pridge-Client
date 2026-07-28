/*
 * SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.
 */

(() => {
  "use strict";

  const { useEffect, useRef, useState } = React;
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

  function setPreview(form) {
    document.documentElement.dataset.darkness = (form.darkness_grade || "Onyx").toLowerCase();
  }

  function ClearLogsConfirm({ onCancel, onConfirm }) {
    return html`
      <div class="modal-backdrop" role="presentation" onMouseDown=${(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}>
        <div class="confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="clear-logs-title" aria-describedby="clear-logs-message">
          <img class="confirm-app-icon" src="assets/Icon.png" alt="" />
          <div class="confirm-copy">
            <h2 id="clear-logs-title">${S.clear_logs_confirm_title}</h2>
            <p id="clear-logs-message">${S.clear_logs_confirm_message}</p>
          </div>
          <div class="confirm-actions">
            <button autoFocus=${true} onClick=${onCancel}>${S.cancel}</button>
            <button class="danger" onClick=${onConfirm}>${S.clear}</button>
          </div>
        </div>
      </div>
    `;
  }

  function Settings() {
    const [form, setForm] = useState(null);
    const [message, setMessage] = useState("");
    const [exporting, setExporting] = useState(false);
    const [exportFrom, setExportFrom] = useState("");
    const [exportTo, setExportTo] = useState("");
    const [choosingFolder, setChoosingFolder] = useState(false);
    const [clearing, setClearing] = useState(false);
    const [showClearConfirm, setShowClearConfirm] = useState(false);
    const saveSequence = useRef(0);

    useEffect(() => {
      whenApiReady(() => {
        callApi("get_state").then((result) => {
          if (!result) return;
          const initial = {
            start_polling_on_launch: result.state.start_polling_on_launch,
            start_at_login: result.state.start_at_login,
            darkness_grade: result.state.appearance.darkness_grade,
            log_file_enabled: result.state.logging.file_enabled,
            log_retention_days: result.state.logging.retention_days,
            log_directory: result.state.logging.directory,
          };
          setForm(initial);
          setPreview(initial);
        });
      });
    }, []);

    if (!form) return html`<div class="loading">${S.loading}</div>`;

    const change = (key, value) => {
      const next = { ...form, [key]: value };
      setForm(next);
      if (key === "darkness_grade") setPreview(next);
      const sequence = ++saveSequence.current;
      setMessage(S.saving_settings);
      callApi("update_application_settings", next).then((result) => {
        if (!result || sequence !== saveSequence.current) return;
        setMessage(result.ok ? S.settings_saved_automatically : (result.error || S.save_failed));
      });
    };

    const chooseLogDirectory = () => {
      setChoosingFolder(true);
      callApi("choose_log_directory").then((result) => {
        setChoosingFolder(false);
        if (!result) return;
        if (!result.ok) {
          setMessage(result.error || S.log_directory_failed);
          return;
        }
        if (result.directory) change("log_directory", result.directory);
      });
    };

    const clearLogs = () => {
      setShowClearConfirm(false);
      setClearing(true);
      setMessage(S.clearing_logs);
      callApi("clear_logs").then((result) => {
        setClearing(false);
        if (!result) return;
        setMessage(result.ok ? S.logs_cleared : (result.error || S.no_logs_to_clear));
      });
    };

    const exportLog = () => {
      setExporting(true);
      setMessage(S.exporting_log);
      callApi("export_log", exportFrom, exportTo).then((result) => {
        setExporting(false);
        if (!result) return;
        setMessage(result.ok ? S.log_exported : (result.error || S.log_export_failed));
      });
    };

    return html`
      <main class="utility-page">
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.settings}</h1><p>${S.about_title}</p></div>
        </div>
        <div class="utility-content">
          <section class="settings-section">
            <h2>${S.appearance}</h2>
            <p>${S.appearance_hint}</p>
            <div class="stone-options" role="radiogroup" aria-label=${S.darkness_amount}>
              ${S.darkness_grades.map(
                (grade) => html`<button
                  type="button"
                  role="radio"
                  aria-checked=${form.darkness_grade === grade.name}
                  class=${form.darkness_grade === grade.name ? "stone-option selected" : "stone-option"}
                  onClick=${() => change("darkness_grade", grade.name)}
                  key=${grade.name}
                >
                  <span class=${`stone-swatch stone-${grade.name.toLowerCase()}`}></span>
                  <span><strong>${grade.name}</strong><small>${grade.tone}</small></span>
                </button>`
              )}
            </div>
          </section>
          <section class="settings-section">
            <h2>${S.startup}</h2>
            <div class="setting-row">
              <div class="setting-copy"><strong>${S.start_polling_on_launch}</strong></div>
              <input class="setting-check" type="checkbox" checked=${form.start_polling_on_launch} onChange=${(event) => change("start_polling_on_launch", event.target.checked)} />
            </div>
            <div class="setting-row">
              <div class="setting-copy"><strong>${S.start_at_login}</strong></div>
              <input class="setting-check" type="checkbox" checked=${form.start_at_login} onChange=${(event) => change("start_at_login", event.target.checked)} />
            </div>
          </section>
          <section class="settings-section">
            <h2>${S.diagnostics}</h2>
            <div class="setting-row">
              <div class="setting-copy"><strong>${S.log_file_enabled}</strong><small>${S.log_file_enabled_hint}</small></div>
              <input class="setting-check" type="checkbox" checked=${form.log_file_enabled} onChange=${(event) => change("log_file_enabled", event.target.checked)} />
            </div>
            ${form.log_file_enabled
              ? html`
                  <div class="setting-row">
                    <div class="setting-copy"><strong>${S.log_retention_days}</strong></div>
                    <div class="field-row">
                      <input
                        type="number"
                        min="1"
                        max="365"
                        value=${form.log_retention_days}
                        onChange=${(event) => change("log_retention_days", event.target.value)}
                      />
                      <span class="seconds-label">${S.days}</span>
                    </div>
                  </div>
                  <div class="setting-row">
                    <div class="setting-copy">
                      <strong>${S.log_directory}</strong>
                      <small>${form.log_directory || S.log_directory_default}</small>
                    </div>
                    <div class="button-row">
                      ${form.log_directory
                        ? html`<button class="ghost" onClick=${() => change("log_directory", "")}>${S.reset_to_default}</button>`
                        : null}
                      <button onClick=${chooseLogDirectory} disabled=${choosingFolder}>
                        ${choosingFolder ? S.choosing_folder : S.choose_folder}
                      </button>
                    </div>
                  </div>
                `
              : null}
            <div class="setting-row">
              <div class="setting-copy"><strong>${S.clear_logs}</strong><small>${S.clear_logs_hint}</small></div>
              <button class="danger" onClick=${() => setShowClearConfirm(true)} disabled=${clearing}>
                ${clearing ? S.clearing_logs : S.clear_logs}
              </button>
            </div>
            <div class="setting-row">
              <div class="setting-copy"><strong>${S.export_log}</strong><small>${S.export_log_hint}</small></div>
              <button onClick=${exportLog} disabled=${exporting}>${exporting ? S.exporting_log : S.export_log}</button>
            </div>
            <div class="setting-row">
              <div class="setting-copy"><small>${S.export_log_range_hint}</small></div>
              <div class="field-row">
                <label class="field-label" for="export-log-from">${S.export_log_range_from}</label>
                <input id="export-log-from" type="date" value=${exportFrom} onChange=${(event) => setExportFrom(event.target.value)} />
                <label class="field-label" for="export-log-to">${S.export_log_range_to}</label>
                <input id="export-log-to" type="date" value=${exportTo} onChange=${(event) => setExportTo(event.target.value)} />
              </div>
            </div>
          </section>
          ${message ? html`<div class="settings-message">${message}</div>` : null}
          ${showClearConfirm
            ? html`<${ClearLogsConfirm} onCancel=${() => setShowClearConfirm(false)} onConfirm=${clearLogs} />`
            : null}
        </div>
        <div class="utility-actions">
          <button onClick=${() => callApi("close_utility_window", "settings")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${Settings} />`);
})();
