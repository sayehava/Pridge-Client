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

  function About() {
    const [state, setState] = useState(null);
    useEffect(() => {
      whenApiReady(() => callApi("get_state").then((result) => {
        if (!result) return;
        document.documentElement.dataset.darkness = (result.state.appearance.darkness_grade || "Onyx").toLowerCase();
        setState(result.state);
      }));
    }, []);

    if (!state) return html`<div class="loading">${S.loading}</div>`;

    return html`
      <main class="utility-page about-page">
        <img class="about-logo" src="assets/Logo.png" alt="PrintBridge" />
        <p class="about-description">${S.about_description}</p>
        <div class="about-details">
          <div class="about-detail"><span>${S.version}</span><strong>${state.version}</strong></div>
          <div class="about-detail"><span>${S.developer}</span><strong>Sayeh Ava Pazouki</strong></div>
          <div class="about-detail"><span>${S.copyright}</span><strong>${S.copyright_value}</strong></div>
        </div>
        <button class="primary" onClick=${() => callApi("close_utility_window", "about")}>${S.close}</button>
      </main>
    `;
  }

  ReactDOM.createRoot(document.getElementById("root")).render(html`<${About} />`);
})();
