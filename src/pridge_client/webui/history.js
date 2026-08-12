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

  function formatTimestamp(iso) {
    const date = new Date(iso);
    return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
  }

  function ClearHistoryConfirm({ onCancel, onConfirm }) {
    return html`
      <div class="modal-backdrop" role="presentation" onMouseDown=${(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}>
        <div class="confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="clear-history-title" aria-describedby="clear-history-message">
          <img class="confirm-app-icon" src="assets/Icon.png" alt="" />
          <div class="confirm-copy">
            <h2 id="clear-history-title">${S.clear_history_confirm_title}</h2>
            <p id="clear-history-message">${S.clear_history_confirm_message}</p>
          </div>
          <div class="confirm-actions">
            <button autoFocus=${true} onClick=${onCancel}>${S.cancel}</button>
            <button class="danger" onClick=${onConfirm}>${S.clear_history}</button>
          </div>
        </div>
      </div>
    `;
  }

  function History() {
    const [jobs, setJobs] = useState(null);
    const [message, setMessage] = useState("");
    const [reprintingId, setReprintingId] = useState("");
    const [clearing, setClearing] = useState(false);
    const [showClearConfirm, setShowClearConfirm] = useState(false);

    const refresh = () => {
      callApi("get_state").then((result) => {
        if (result) document.documentElement.dataset.darkness = (result.state.appearance.darkness_grade || "Onyx").toLowerCase();
      });
      callApi("list_archived_jobs").then((result) => {
        if (!result) return;
        setJobs(result.ok ? result.jobs : []);
      });
    };

    useEffect(() => {
      whenApiReady(refresh);
    }, []);

    const reprint = (job) => {
      setReprintingId(job.id);
      setMessage("");
      callApi("reprint_job", job.id).then((result) => {
        setReprintingId("");
        if (!result) return;
        setMessage(result.ok ? (result.message || S.reprint_submitted) : (result.error || S.reprint_failed));
        if (result.ok) refresh();
      });
    };

    const clearHistory = () => {
      setShowClearConfirm(false);
      setClearing(true);
      callApi("clear_archive").then((result) => {
        setClearing(false);
        if (!result) return;
        setMessage(result.ok ? (result.message || S.history_cleared) : (result.error || S.save_failed));
        if (result.ok) refresh();
      });
    };

    if (jobs === null) return html`<div class="loading">${S.loading}</div>`;

    return html`
      <main class="utility-page">
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.history}</h1><p>${S.history_hint}</p></div>
        </div>
        <div class="utility-content">
          <section class="settings-section">
            ${jobs.length === 0
              ? html`<p class="hint-text">${S.no_archived_jobs}</p>`
              : jobs.map(
                  (job) => html`
                    <div class="setting-row" key=${job.id}>
                      <div class="setting-copy">
                        <strong>${job.printer_name}</strong>
                        <small>
                          ${formatTimestamp(job.created_at)}${job.filename ? ` · ${job.filename}` : ""}${job.copies > 1 ? ` · ${job.copies}x` : ""}
                        </small>
                        ${job.status === "failed" && job.detail ? html`<small class="hint-text">${job.detail}</small>` : null}
                      </div>
                      <div class="button-row">
                        <span class=${job.status === "failed" ? "badge badge-error" : "badge badge-active"}>${job.status}</span>
                        <button onClick=${() => reprint(job)} disabled=${reprintingId === job.id}>
                          ${reprintingId === job.id ? S.reprinting : S.reprint}
                        </button>
                      </div>
                    </div>
                  `
                )}
          </section>
          ${message ? html`<div class="settings-message">${message}</div>` : null}
          ${showClearConfirm
            ? html`<${ClearHistoryConfirm} onCancel=${() => setShowClearConfirm(false)} onConfirm=${clearHistory} />`
            : null}
        </div>
        <div class="utility-actions">
          <button class="danger" onClick=${() => setShowClearConfirm(true)} disabled=${clearing || jobs.length === 0}>
            ${clearing ? S.clearing_history : S.clear_history}
          </button>
          <button onClick=${() => callApi("close_utility_window", "history")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${History} />`);
})();
