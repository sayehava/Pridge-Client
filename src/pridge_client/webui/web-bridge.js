// SPDX-FileCopyrightText: 2026 Sayeh Ava Pazouki
// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileComment: Additional terms apply; see ADDITIONAL_TERMS.md.

(function () {
  "use strict";

  window.PridgeBrowserMode = true;

  const utilityPages = {
    open_about_window: "about.html",
    open_app_mapping_window: "app-mapping.html",
    open_history_window: "history.html",
    open_plugins_window: "plugins.html",
    open_printers_window: "printers.html",
    open_servers_window: "servers.html",
    open_settings_window: "settings.html",
  };

  function sendModal(action, page) {
    window.parent.postMessage({ source: "pridge-browser", action, page }, window.location.origin);
    return Promise.resolve(null);
  }

  function openServer(serverId) {
    const query = new URLSearchParams({ server_id: serverId || "", window_key: "browser" });
    return sendModal("open", `server.html?${query}`);
  }

  function openReceiptComposer(serverId, remotePrinterId) {
    const open = () => sendModal("open", "receipt-composer.html");
    if (!serverId || !remotePrinterId) return open();
    return rpc("set_pending_receipt_selection", [serverId, remotePrinterId]).then(open);
  }

  function navigate(method, args) {
    if (utilityPages[method]) return sendModal("open", utilityPages[method]);
    if (method === "open_server_window") return openServer(args[0]);
    if (method === "open_receipt_composer_window") return openReceiptComposer(args[0], args[1]);
    if (method === "open_plugin_settings_window") {
      const pages = { app_mapping: "app-mapping.html", receipt_composer: "receipt-composer.html" };
      return pages[args[0]] ? sendModal("open", pages[args[0]]) : Promise.resolve(null);
    }
    if (method === "close_server_window" || method === "close_utility_window") {
      return sendModal("close", "");
    }
    return null;
  }

  async function rpc(method, args) {
    const response = await fetch("/api/rpc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ method, args }),
    });
    return response.json();
  }

  const api = new Proxy({}, {
    get(_target, method) {
      return (...args) => navigate(String(method), args) || rpc(String(method), args);
    },
  });

  window.pywebview = { api };
}());
