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

  function Settings() {
    const [form, setForm] = useState(null);
    const [message, setMessage] = useState("");
    const [exporting, setExporting] = useState(false);
    const [plugins, setPlugins] = useState(null);
    const saveSequence = useRef(0);

    useEffect(() => {
      whenApiReady(() => {
        callApi("get_state").then((result) => {
          if (!result) return;
          const initial = {
            start_polling_on_launch: result.state.start_polling_on_launch,
            start_at_login: result.state.start_at_login,
            darkness_grade: result.state.appearance.darkness_grade,
          };
          setForm(initial);
          setPreview(initial);
        });
        callApi("get_renderer_plugins").then((result) => {
          if (result && result.ok) setPlugins(result.plugins);
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

    const togglePlugin = (pluginId, enabled) => {
      callApi("set_renderer_plugin_enabled", pluginId, enabled).then((result) => {
        if (result && result.ok) setPlugins(result.plugins);
      });
    };

    const movePlugin = (index, direction) => {
      if (!plugins) return;
      const sorted = [...plugins].sort((a, b) => a.priority - b.priority);
      const target = index + direction;
      if (target < 0 || target >= sorted.length) return;
      callApi("swap_renderer_plugin_priorities", sorted[index].plugin_id, sorted[target].plugin_id).then((result) => {
        if (result && result.ok) setPlugins(result.plugins);
      });
    };

    const exportLog = () => {
      setExporting(true);
      setMessage(S.exporting_log);
      callApi("export_log").then((result) => {
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
          <h2>${S.renderers}</h2>
          <p>${S.renderers_hint}</p>
          ${!plugins ? null : plugins.length === 0 ? html`<p class="hint-text">${S.no_renderers}</p>` : (() => {
            const sorted = [...plugins].sort((a, b) => a.priority - b.priority);
            return sorted.map((plugin, index) => html`
              <div class="setting-row renderer-row" key=${plugin.plugin_id}>
                <input
                  class="setting-check"
                  type="checkbox"
                  checked=${plugin.enabled}
                  disabled=${!!plugin.load_error}
                  onChange=${(e) => togglePlugin(plugin.plugin_id, e.target.checked)}
                />
                <div class="setting-copy">
                  <strong>${plugin.display_name}</strong>
                  <small>${plugin.plugin_id} · v${plugin.version || "?"} · API ${plugin.api_version}</small>
                  ${plugin.mime_types.length ? html`<small class="renderer-types">${plugin.mime_types.join(", ")}</small>` : null}
                  ${plugin.load_error ? html`<small class="renderer-error">${S.renderer_load_error}: ${plugin.load_error}</small>` : null}
                </div>
                <div class="renderer-order">
                  <button
                    class="renderer-order-btn"
                    title=${S.renderer_move_up}
                    disabled=${index === 0}
                    onClick=${() => movePlugin(index, -1)}
                  >↑</button>
                  <button
                    class="renderer-order-btn"
                    title=${S.renderer_move_down}
                    disabled=${index === sorted.length - 1}
                    onClick=${() => movePlugin(index, 1)}
                  >↓</button>
                </div>
              </div>
            `);
          })()}
        </section>
        <section class="settings-section">
          <h2>${S.diagnostics}</h2>
          <div class="setting-row">
            <div class="setting-copy"><strong>${S.export_log}</strong><small>${S.export_log_hint}</small></div>
            <button onClick=${exportLog} disabled=${exporting}>${exporting ? S.exporting_log : S.export_log}</button>
          </div>
        </section>
        ${message ? html`<div class="settings-message">${message}</div>` : null}
        <div class="utility-actions">
          <button onClick=${() => callApi("close_utility_window", "settings")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${Settings} />`);
})();
