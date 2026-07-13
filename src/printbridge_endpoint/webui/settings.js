(() => {
  "use strict";

  const { useEffect, useState } = React;
  const html = htm.bind(React.createElement);
  const S = window.PrintBridgeStrings;

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
    const opacity = form.transparency_enabled ? Number(form.glass_opacity_percent) / 100 : 0.97;
    document.documentElement.style.setProperty("--window-opacity", String(opacity));
  }

  function Settings() {
    const [form, setForm] = useState(null);
    const [message, setMessage] = useState("");
    const [restartRequired, setRestartRequired] = useState(false);

    useEffect(() => {
      whenApiReady(() => callApi("get_state").then((result) => {
        if (!result) return;
        const initial = {
          start_polling_on_launch: result.state.start_polling_on_launch,
          start_at_login: result.state.start_at_login,
          transparency_enabled: result.state.appearance.transparency_enabled,
          glass_opacity_percent: result.state.appearance.glass_opacity_percent,
        };
        setForm(initial);
        setPreview(initial);
      }));
    }, []);

    if (!form) return html`<div class="loading">${S.loading}</div>`;

    const change = (key, value) => {
      const next = { ...form, [key]: value };
      setForm(next);
      if (key === "transparency_enabled" || key === "glass_opacity_percent") setPreview(next);
    };
    const save = () => callApi("update_application_settings", form).then((result) => {
      if (!result) return;
      setMessage(result.message || S.settings_saved);
      setRestartRequired(Boolean(result.restart_required));
    });

    return html`
      <main class="utility-page">
        <div class="utility-hero">
          <img src="assets/Hero.png" alt="" />
          <div class="utility-hero-copy"><h1>${S.settings}</h1><p>${S.about_title}</p></div>
        </div>
        <section class="settings-section">
          <h2>${S.appearance}</h2>
          <p>${S.appearance_hint}</p>
          <div class="setting-row">
            <div class="setting-copy"><strong>${S.native_transparency}</strong><small>${S.native_transparency_hint}</small></div>
            <input class="setting-check" type="checkbox" checked=${form.transparency_enabled} onChange=${(event) => change("transparency_enabled", event.target.checked)} />
          </div>
          <div class="setting-row">
            <div class="setting-copy"><strong>${S.glass_opacity}</strong><small>${S.glass_opacity_hint}</small></div>
            <div class="opacity-control">
              <input type="range" min="25" max="95" value=${form.glass_opacity_percent} onInput=${(event) => change("glass_opacity_percent", event.target.value)} />
              <span class="opacity-value">${form.glass_opacity_percent}%</span>
            </div>
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
        ${message ? html`<div class=${restartRequired ? "settings-message restart" : "settings-message"}>${restartRequired ? S.restart_required : message}</div>` : null}
        <div class="utility-actions">
          <button onClick=${() => callApi("close_utility_window", "settings")}>${S.close}</button>
          <button class="primary" onClick=${save}>${S.save}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${Settings} />`);
})();
