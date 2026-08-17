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

  function browserDialog(message, promptValue) {
    return new Promise((resolve) => {
      const hasInput = promptValue !== undefined;
      const backdrop = document.createElement("div");
      backdrop.className = "modal-backdrop";
      const modal = document.createElement("div");
      modal.className = "confirm-modal";
      modal.setAttribute("role", "alertdialog");
      modal.setAttribute("aria-modal", "true");
      const icon = document.createElement("img");
      icon.className = "confirm-app-icon";
      icon.src = "/assets/Icon.png";
      icon.alt = "";
      const copy = document.createElement("div");
      copy.className = "confirm-copy";
      const heading = document.createElement("h2");
      heading.textContent = hasInput ? "Set counter value" : "Confirm action";
      const detail = document.createElement("p");
      detail.textContent = message;
      const input = hasInput ? document.createElement("input") : null;
      if (input) {
        input.type = "number";
        input.value = String(promptValue);
        input.min = "0";
      }
      copy.append(heading, detail);
      if (input) copy.append(input);
      const actions = document.createElement("div");
      actions.className = "confirm-actions";
      const cancel = document.createElement("button");
      cancel.textContent = (window.PridgeStrings && window.PridgeStrings.cancel) || "Cancel";
      const confirm = document.createElement("button");
      confirm.className = hasInput ? "primary" : "danger";
      confirm.textContent = hasInput ? "Set" : ((window.PridgeStrings && window.PridgeStrings.remove) || "Remove");
      actions.append(cancel, confirm);
      modal.append(icon, copy, actions);
      backdrop.append(modal);
      const finish = (value) => {
        backdrop.remove();
        resolve(value);
      };
      cancel.addEventListener("click", () => finish(hasInput ? null : false));
      confirm.addEventListener("click", () => finish(hasInput ? input.value : true));
      backdrop.addEventListener("mousedown", (event) => {
        if (event.target === backdrop) finish(hasInput ? null : false);
      });
      document.body.append(backdrop);
      (input || cancel).focus();
    });
  }

  window.PridgeBrowserConfirm = (message) => browserDialog(message);
  window.PridgeBrowserPrompt = (message, initialValue) => browserDialog(message, initialValue);

  const api = new Proxy({}, {
    get(_target, method) {
      return (...args) => navigate(String(method), args) || rpc(String(method), args);
    },
  });

  window.pywebview = { api };
}());
