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

  function emptyMappingForm() {
    return { name: "", extensions: "", mime_types: "", executable: "", arguments: "", timeout: "60", platform_filter: "", enabled: true };
  }

  function mappingToForm(m) {
    return {
      name: m.name,
      extensions: m.extensions.join(", "),
      mime_types: m.mime_types.join(", "),
      executable: m.executable,
      arguments: m.arguments.join("\n"),
      timeout: String(m.timeout),
      platform_filter: m.platform_filter,
      enabled: m.enabled,
    };
  }

  function formToMappingFields(form) {
    return {
      name: form.name.trim(),
      extensions: form.extensions.split(",").map((s) => s.trim()).filter(Boolean),
      mime_types: form.mime_types.split(",").map((s) => s.trim()).filter(Boolean),
      executable: form.executable.trim(),
      arguments: form.arguments.split("\n").map((s) => s.trim()).filter(Boolean),
      timeout: parseFloat(form.timeout) || 60,
      platform_filter: form.platform_filter,
      enabled: form.enabled,
    };
  }

  function MappingForm({ initial, onSave, onCancel }) {
    const [form, setForm] = useState(initial || emptyMappingForm());
    const set = (key, val) => setForm((prev) => ({ ...prev, [key]: val }));
    return html`
      <div class="mapping-form">
        <div class="mapping-form-row">
          <label>${S.mapping_name}</label>
          <input type="text" value=${form.name} onInput=${(e) => set("name", e.target.value)} placeholder="Adobe Photoshop" />
        </div>
        <div class="mapping-form-row">
          <label>${S.mapping_extensions}</label>
          <input type="text" value=${form.extensions} onInput=${(e) => set("extensions", e.target.value)} placeholder=${S.mapping_extensions_hint} />
        </div>
        <div class="mapping-form-row">
          <label>${S.mapping_mime_types}</label>
          <input type="text" value=${form.mime_types} onInput=${(e) => set("mime_types", e.target.value)} placeholder=${S.mapping_mime_types_hint} />
        </div>
        <div class="mapping-form-row">
          <label>${S.mapping_executable}</label>
          <input type="text" value=${form.executable} onInput=${(e) => set("executable", e.target.value)} placeholder="/usr/bin/convert" />
        </div>
        <div class="mapping-form-row mapping-form-row--tall">
          <label>${S.mapping_arguments}<small>${S.mapping_arguments_hint}</small></label>
          <textarea rows="3" value=${form.arguments} onInput=${(e) => set("arguments", e.target.value)} placeholder="{input}\n--output\n{output}" />
        </div>
        <div class="mapping-form-row mapping-form-row--half">
          <div class="mapping-form-row">
            <label>${S.mapping_timeout}</label>
            <input type="number" min="1" step="1" value=${form.timeout} onInput=${(e) => set("timeout", e.target.value)} />
          </div>
          <div class="mapping-form-row">
            <label>${S.mapping_platform}</label>
            <select value=${form.platform_filter} onChange=${(e) => set("platform_filter", e.target.value)}>
              <option value="">${S.mapping_platform_all}</option>
              <option value="windows">${S.mapping_platform_windows}</option>
              <option value="darwin">${S.mapping_platform_macos}</option>
              <option value="linux">${S.mapping_platform_linux}</option>
            </select>
          </div>
        </div>
        <div class="mapping-form-actions">
          <button onClick=${() => onSave(formToMappingFields(form))} disabled=${!form.name.trim() || !form.executable.trim()}>${S.mapping_save}</button>
          <button class="btn-secondary" onClick=${onCancel}>${S.mapping_cancel}</button>
        </div>
      </div>
    `;
  }

  function Settings() {
    const [form, setForm] = useState(null);
    const [message, setMessage] = useState("");
    const [exporting, setExporting] = useState(false);
    const [plugins, setPlugins] = useState(null);
    const [mappings, setMappings] = useState(null);
    const [editingMapping, setEditingMapping] = useState(null);
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
        callApi("get_app_mappings").then((result) => {
          if (result && result.ok) setMappings(result.mappings);
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

    const saveMapping = (fields) => {
      const promise = editingMapping && editingMapping.id
        ? callApi("update_app_mapping", editingMapping.id, fields)
        : callApi("add_app_mapping", fields);
      promise.then((result) => {
        if (result && result.ok) {
          setMappings(result.mappings);
          setEditingMapping(null);
        }
      });
    };

    const removeMapping = (mappingId, name) => {
      if (!window.confirm(S.mapping_remove_confirm.replace("{name}", name))) return;
      callApi("remove_app_mapping", mappingId).then((result) => {
        if (result && result.ok) setMappings(result.mappings);
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
          <div class="app-mappings-section">
            <h3>${S.app_mappings}</h3>
            <p>${S.app_mappings_hint}</p>
            ${mappings !== null && mappings.length === 0 && editingMapping === null
              ? html`<p class="hint-text">${S.no_app_mappings}</p>`
              : null}
            ${mappings !== null ? mappings.map((m) => editingMapping && editingMapping.id === m.id
              ? html`<${MappingForm} key=${m.id} initial=${mappingToForm(m)} onSave=${saveMapping} onCancel=${() => setEditingMapping(null)} />`
              : html`
                <div class="setting-row mapping-row" key=${m.id}>
                  <input
                    class="setting-check"
                    type="checkbox"
                    checked=${m.enabled}
                    onChange=${(e) => callApi("update_app_mapping", m.id, { enabled: e.target.checked }).then((r) => r && r.ok && setMappings(r.mappings))}
                  />
                  <div class="setting-copy">
                    <strong>${m.name}</strong>
                    ${[...m.extensions, ...m.mime_types].length ? html`<small>${[...m.extensions, ...m.mime_types].join(", ")}</small>` : null}
                    ${m.executable ? html`<small class="renderer-types">${m.executable}</small>` : null}
                  </div>
                  <div class="mapping-actions">
                    <button class="btn-secondary" onClick=${() => setEditingMapping(m)}>${S.edit}</button>
                    <button class="btn-danger-small" onClick=${() => removeMapping(m.id, m.name)}>${S.remove}</button>
                  </div>
                </div>
              `
            ) : null}
            ${editingMapping && !editingMapping.id
              ? html`<${MappingForm} initial=${null} onSave=${saveMapping} onCancel=${() => setEditingMapping(null)} />`
              : null}
            ${editingMapping === null
              ? html`<button class="btn-secondary mapping-add-btn" onClick=${() => setEditingMapping({})}>${S.add_mapping}</button>`
              : null}
          </div>
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
