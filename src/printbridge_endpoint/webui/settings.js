(() => {
  "use strict";

  const { useEffect, useRef, useState } = React;
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
    document.documentElement.dataset.darkness = (form.darkness_grade || "Onyx").toLowerCase();
  }

  function Settings() {
    const [form, setForm] = useState(null);
    const [message, setMessage] = useState("");
    const saveSequence = useRef(0);

    useEffect(() => {
      whenApiReady(() => callApi("get_state").then((result) => {
        if (!result) return;
        const initial = {
          start_polling_on_launch: result.state.start_polling_on_launch,
          start_at_login: result.state.start_at_login,
          darkness_grade: result.state.appearance.darkness_grade,
        };
        setForm(initial);
        setPreview(initial);
      }));
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
        ${message ? html`<div class="settings-message">${message}</div>` : null}
        <div class="utility-actions">
          <button onClick=${() => callApi("close_utility_window", "settings")}>${S.close}</button>
        </div>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${Settings} />`);
})();
