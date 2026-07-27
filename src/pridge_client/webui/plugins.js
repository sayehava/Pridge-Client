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

  function Plugins() {
    const [plugins, setPlugins] = useState(null);
    const [message, setMessage] = useState("");
    const [busy, setBusy] = useState(false);
    const [draggingId, setDraggingId] = useState(null);

    const refreshPlugins = () => {
      callApi("get_renderer_plugins").then((result) => {
        if (result && result.ok) setPlugins(result.plugins);
      });
    };

    useEffect(() => {
      whenApiReady(refreshPlugins);
    }, []);

    const togglePlugin = (pluginId, enabled) => {
      callApi("set_renderer_plugin_enabled", pluginId, enabled).then((result) => {
        if (result && result.ok) setPlugins(result.plugins);
      });
    };

    const reorderPlugin = (pluginId, targetIndex) => {
      callApi("reorder_renderer_plugin", pluginId, targetIndex).then((result) => {
        if (result && result.ok) setPlugins(result.plugins);
      });
    };
    const dropAt = (targetIndex) => {
      if (draggingId) reorderPlugin(draggingId, targetIndex);
      setDraggingId(null);
    };

    const installPlugin = () => {
      setBusy(true);
      setMessage(S.installing_plugin);
      callApi("install_plugin").then((result) => {
        setBusy(false);
        if (!result) return;
        if (result.plugins) setPlugins(result.plugins);
        setMessage(result.ok ? (result.message || S.plugin_installed) : (result.error || S.plugin_install_failed));
      });
    };

    const removePlugin = (pluginId, name) => {
      if (!window.confirm(S.plugin_remove_confirm.replace("{name}", name))) return;
      callApi("remove_plugin", pluginId).then((result) => {
        if (!result) return;
        if (result.plugins) setPlugins(result.plugins);
        setMessage(result.ok ? (result.message || S.plugin_removed) : (result.error || S.plugin_remove_failed));
      });
    };

    const rescanPlugins = () => {
      setBusy(true);
      setMessage(S.rescanning_plugins);
      callApi("rescan_plugins").then((result) => {
        setBusy(false);
        if (!result) return;
        if (result.plugins) setPlugins(result.plugins);
        setMessage(result.ok ? S.plugins_rescanned : (result.error || S.plugin_install_failed));
      });
    };

    const openPluginSettings = () => {
      callApi("open_app_mapping_window");
    };

    return html`
      <main class="utility-page">
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.plugins}</h1><p>${S.plugins_hint}</p></div>
        </div>
        <section class="settings-section">
          <h2>${S.renderers}</h2>
          <p>${S.renderers_hint}</p>
          ${!plugins ? null : plugins.length === 0 ? html`<p class="hint-text">${S.no_renderers}</p>` : (() => {
            const sorted = [...plugins].sort((a, b) => a.priority - b.priority);
            return html`
              <div
                onDragOver=${(event) => event.preventDefault()}
                onDrop=${(event) => {
                  event.preventDefault();
                  dropAt(sorted.length - 1);
                }}
              >
                ${sorted.map((plugin, index) => {
                  const thirdParty = !plugin.is_builtin && !!plugin.source_path;
                  return html`
                    <div
                      class=${"setting-row renderer-row" + (draggingId === plugin.plugin_id ? " widget-card-dragging" : "")}
                      key=${plugin.plugin_id}
                      onDragOver=${(event) => event.preventDefault()}
                      onDrop=${(event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        dropAt(index);
                      }}
                    >
                      <span
                        class="widget-drag-handle"
                        draggable="true"
                        title=${S.drag_to_reorder}
                        onDragStart=${(event) => {
                          event.dataTransfer.effectAllowed = "move";
                          setDraggingId(plugin.plugin_id);
                        }}
                        onDragEnd=${() => setDraggingId(null)}
                      >⋮⋮</span>
                      <input
                        class="setting-check"
                        type="checkbox"
                        checked=${plugin.enabled}
                        disabled=${!!plugin.load_error}
                        onChange=${(e) => togglePlugin(plugin.plugin_id, e.target.checked)}
                      />
                      <div class="setting-copy">
                        <strong>${plugin.display_name}</strong>
                        <span class=${thirdParty ? "badge" : "badge badge-active"}>${thirdParty ? S.renderer_third_party : S.renderer_builtin}</span>
                        <small>${plugin.plugin_id} · v${plugin.version || "?"} · API ${plugin.api_version}</small>
                        ${plugin.mime_types.length ? html`<small class="renderer-types">${plugin.mime_types.join(", ")}</small>` : null}
                        ${thirdParty ? html`<small class="renderer-types">${plugin.source_path}</small>` : null}
                        ${plugin.load_error ? html`<small class="renderer-error">${S.renderer_load_error}: ${plugin.load_error}</small>` : null}
                      </div>
                      ${plugin.has_settings ? html`<button class="btn-secondary" onClick=${openPluginSettings}>${S.plugin_settings}</button>` : null}
                      ${thirdParty ? html`<button class="btn-danger-small" onClick=${() => removePlugin(plugin.plugin_id, plugin.display_name)}>${S.remove}</button>` : null}
                    </div>
                  `;
                })}
              </div>
            `;
          })()}
          <div class="plugin-install-row">
            <button onClick=${installPlugin} disabled=${busy}>${busy ? S.installing_plugin : S.install_plugin}</button>
            <button class="btn-secondary" onClick=${rescanPlugins} disabled=${busy}>${S.rescan_plugins}</button>
          </div>
          <p class="hint-text">${S.install_plugin_hint}</p>
        </section>
        ${message ? html`<div class="settings-message">${message}</div>` : null}
        <div class="utility-actions">
          <button onClick=${() => callApi("close_utility_window", "plugins")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${Plugins} />`);
})();
