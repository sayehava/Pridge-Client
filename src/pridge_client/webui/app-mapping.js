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

  function AppMappingSettings() {
    const [mappings, setMappings] = useState(null);
    const [editingMapping, setEditingMapping] = useState(null);

    useEffect(() => {
      whenApiReady(() => {
        callApi("get_app_mappings").then((result) => {
          if (result && result.ok) setMappings(result.mappings);
        });
      });
    }, []);

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

    return html`
      <main class="utility-page">
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.app_mappings}</h1><p>${S.app_mappings_hint}</p></div>
        </div>
        <section class="settings-section">
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
        </section>
        <div class="utility-actions">
          <button onClick=${() => callApi("close_utility_window", "app_mapping")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${AppMappingSettings} />`);
})();
