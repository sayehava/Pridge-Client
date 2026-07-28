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

  const ALL_TAB = "__all__";

  // Resolves where a drag-and-drop reorder should land: `items` is the
  // current sorted list, `fromId` the dragged item, `targetId` the item
  // it's hovering over (null = the end), `placeAfter` which side of the
  // target. Returns the resulting index in post-removal terms, which is
  // what the reorder_renderer_plugin/reorder_dashboard_widget APIs expect -
  // computed this way (id-relative, not a raw hovered-row index) so the
  // same target always means the same thing regardless of which direction
  // the drag came from.
  function resolveDropIndex(items, fromId, targetId, idKey, placeAfter) {
    const withoutDragged = items.filter((item) => item[idKey] !== fromId);
    if (targetId == null) return withoutDragged.length;
    const targetIndex = withoutDragged.findIndex((item) => item[idKey] === targetId);
    return targetIndex === -1 ? withoutDragged.length : placeAfter ? targetIndex + 1 : targetIndex;
  }

  function Plugins() {
    const [plugins, setPlugins] = useState(null);
    const [message, setMessage] = useState("");
    const [busy, setBusy] = useState(false);
    const [draggingId, setDraggingId] = useState(null);
    const [dropTargetId, setDropTargetId] = useState(null);
    const [dropAfter, setDropAfter] = useState(false);
    const [activeTab, setActiveTab] = useState(ALL_TAB);
    const [statusFilter, setStatusFilter] = useState("all");

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

    const reorderPlugin = (pluginId, category, targetIndex) => {
      callApi("reorder_renderer_plugin", pluginId, targetIndex, category).then((result) => {
        if (result && result.ok) setPlugins(result.plugins);
      });
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

    const openPluginSettings = (settingsWindow) => {
      callApi("open_plugin_settings_window", settingsWindow);
    };

    const categoryLabel = (category) => category || S.plugin_category_unknown;
    const matchesFilter = (plugin) =>
      statusFilter === "all" || (statusFilter === "active" ? plugin.enabled : !plugin.enabled);

    const categories = plugins
      ? Array.from(new Set(plugins.map((plugin) => plugin.category))).sort((a, b) =>
          categoryLabel(a).localeCompare(categoryLabel(b))
        )
      : [];
    const countFor = (category) => (plugins || []).filter((plugin) => plugin.category === category).length;

    const clearDropTarget = () => {
      setDropTargetId(null);
      setDropAfter(false);
    };

    const moveBy = (groupPlugins, plugin, delta) => {
      const index = groupPlugins.findIndex((p) => p.plugin_id === plugin.plugin_id);
      const neighborIndex = index + delta;
      if (index === -1 || neighborIndex < 0 || neighborIndex >= groupPlugins.length) return;
      const neighbor = groupPlugins[neighborIndex];
      const targetIndex = resolveDropIndex(groupPlugins, plugin.plugin_id, neighbor.plugin_id, "plugin_id", delta > 0);
      reorderPlugin(plugin.plugin_id, plugin.category, targetIndex);
    };

    const renderRow = (plugin, index, groupPlugins, finishDrop) => {
      const thirdParty = !plugin.is_builtin && !!plugin.source_path;
      return html`
        <div
          class=${[
            "setting-row",
            "renderer-row",
            draggingId === plugin.plugin_id ? "widget-card-dragging" : "",
            dropTargetId === plugin.plugin_id && !dropAfter ? "dnd-drop-before" : "",
            dropTargetId === plugin.plugin_id && dropAfter ? "dnd-drop-after" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          key=${plugin.plugin_id}
          onDragOver=${(event) => {
            event.preventDefault();
            if (draggingId == null) return;
            const rect = event.currentTarget.getBoundingClientRect();
            setDropTargetId(plugin.plugin_id);
            setDropAfter(event.clientY - rect.top > rect.height / 2);
          }}
          onDrop=${finishDrop}
        >
          <span
            class="widget-drag-handle"
            draggable="true"
            title=${S.drag_to_reorder}
            onDragStart=${(event) => {
              event.dataTransfer.effectAllowed = "move";
              setDraggingId(plugin.plugin_id);
            }}
            onDragEnd=${() => {
              setDraggingId(null);
              clearDropTarget();
            }}
          >⋮⋮</span>
          <div class="dnd-move-buttons">
            <button
              type="button"
              class="dnd-move-btn"
              title=${S.receipt_move_up}
              disabled=${index === 0}
              onClick=${() => moveBy(groupPlugins, plugin, -1)}
            >▲</button>
            <button
              type="button"
              class="dnd-move-btn"
              title=${S.receipt_move_down}
              disabled=${index === groupPlugins.length - 1}
              onClick=${() => moveBy(groupPlugins, plugin, 1)}
            >▼</button>
          </div>
          <input
            class="setting-check"
            type="checkbox"
            checked=${plugin.enabled}
            disabled=${!!plugin.load_error}
            onChange=${(e) => togglePlugin(plugin.plugin_id, e.target.checked)}
          />
          <div class="setting-copy">
            <strong>${plugin.display_name}</strong>
            <span class=${thirdParty ? "badge" : "badge badge-active"}>${thirdParty ? S.renderer_third_party : S.plugin_core}</span>
            <small>${plugin.plugin_id} · v${plugin.version || "?"} · API ${plugin.api_version}</small>
            ${plugin.mime_types.length ? html`<small class="renderer-types">${plugin.mime_types.join(", ")}</small>` : null}
            ${thirdParty ? html`<small class="renderer-types">${plugin.source_path}</small>` : null}
            ${plugin.load_error ? html`<small class="renderer-error">${S.renderer_load_error}: ${plugin.load_error}</small>` : null}
          </div>
          ${plugin.has_settings ? html`<button class="btn-secondary" onClick=${() => openPluginSettings(plugin.settings_window)}>${S.plugin_settings}</button>` : null}
          ${thirdParty ? html`<button class="btn-danger-small" onClick=${() => removePlugin(plugin.plugin_id, plugin.display_name)}>${S.remove}</button>` : null}
        </div>
      `;
    };

    const renderGroup = (category, showHeading) => {
      const groupPlugins = (plugins || [])
        .filter((plugin) => plugin.category === category)
        .sort((a, b) => a.priority - b.priority)
        .filter(matchesFilter);
      if (groupPlugins.length === 0) return null;

      const finishDrop = (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (draggingId != null) {
          const targetIndex = resolveDropIndex(groupPlugins, draggingId, dropTargetId, "plugin_id", dropAfter);
          reorderPlugin(draggingId, category, targetIndex);
        }
        setDraggingId(null);
        clearDropTarget();
      };

      return html`
        <div key=${category || "__uncategorized__"}>
          ${showHeading ? html`<div class="plugin-category-separator"><span>${categoryLabel(category)}</span></div>` : null}
          <div>
            ${groupPlugins.map((plugin, index) => renderRow(plugin, index, groupPlugins, finishDrop))}
            ${draggingId != null && groupPlugins.some((plugin) => plugin.plugin_id === draggingId)
              ? html`
                  <div
                    class=${"dnd-drop-end" + (dropTargetId === null ? " dnd-drop-end-active" : "")}
                    onDragOver=${(event) => {
                      event.preventDefault();
                      setDropTargetId(null);
                      setDropAfter(false);
                    }}
                    onDrop=${finishDrop}
                  >
                    ${S.drop_at_end}
                  </div>
                `
              : null}
          </div>
        </div>
      `;
    };

    const groupsToRender = activeTab === ALL_TAB ? categories : [activeTab];
    const renderedGroups = groupsToRender.map((category) => renderGroup(category, activeTab === ALL_TAB)).filter(Boolean);

    return html`
      <main class="utility-page">
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.plugins}</h1><p>${S.plugins_hint}</p></div>
        </div>
        <div class="utility-content">
        <section class="settings-section">
          <div class="plugins-layout">
            <nav class="plugin-category-tabs">
              <button
                class=${activeTab === ALL_TAB ? "plugin-category-tab active" : "plugin-category-tab"}
                onClick=${() => setActiveTab(ALL_TAB)}
              >
                <span>${S.plugins_all_tab}</span>
                <span class="plugin-category-tab-count">${plugins ? plugins.length : 0}</span>
              </button>
              ${categories.map(
                (category) => html`
                  <button
                    class=${activeTab === category ? "plugin-category-tab active" : "plugin-category-tab"}
                    onClick=${() => setActiveTab(category)}
                    key=${category || "__uncategorized__"}
                  >
                    <span>${categoryLabel(category)}</span>
                    <span class="plugin-category-tab-count">${countFor(category)}</span>
                  </button>
                `
              )}
            </nav>
            <div class="plugin-category-content">
              <div class="plugin-filter-row">
                <button class=${statusFilter === "all" ? "primary" : "ghost"} onClick=${() => setStatusFilter("all")}>${S.plugin_filter_all}</button>
                <button class=${statusFilter === "active" ? "primary" : "ghost"} onClick=${() => setStatusFilter("active")}>${S.plugin_filter_active}</button>
                <button class=${statusFilter === "inactive" ? "primary" : "ghost"} onClick=${() => setStatusFilter("inactive")}>${S.plugin_filter_inactive}</button>
              </div>
              ${!plugins
                ? null
                : plugins.length === 0
                ? html`<p class="hint-text">${S.no_plugins}</p>`
                : renderedGroups.length === 0
                ? html`<p class="hint-text">${S.no_plugins_match_filter}</p>`
                : renderedGroups}
              <div class="plugin-install-row">
                <button onClick=${installPlugin} disabled=${busy}>${busy ? S.installing_plugin : S.install_plugin}</button>
                <button class="btn-secondary" onClick=${rescanPlugins} disabled=${busy}>${S.rescan_plugins}</button>
              </div>
              <p class="hint-text">${S.install_plugin_hint}</p>
            </div>
          </div>
        </section>
        ${message ? html`<div class="settings-message">${message}</div>` : null}
        </div>
        <div class="utility-actions">
          <span class="utility-footer-info">${S.plugins_count.replace("{count}", plugins ? plugins.length : 0)}</span>
          <button onClick=${() => callApi("close_utility_window", "plugins")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${Plugins} />`);
})();
