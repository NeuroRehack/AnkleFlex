/**
 * AnkleFlex — Theme switcher
 * Applies a data-theme attribute to <html> and persists the choice.
 * Must be loaded AFTER app.js (placed at end of <body>).
 */
(function () {
  "use strict";

  const THEMES      = ["ocean", "midnight", "clinical", "teal"];
  const STORAGE_KEY = "ankleflex-theme";

  function applyTheme(name) {
    if (!THEMES.includes(name)) name = "ocean";

    // Set attribute on <html> so CSS selectors fire correctly
    document.documentElement.setAttribute("data-theme", name);

    // Update swatch active states
    document.querySelectorAll(".swatch").forEach(function (el) {
      el.classList.toggle("active", el.dataset.theme === name);
    });

    // Persist
    try { localStorage.setItem(STORAGE_KEY, name); } catch (_) {}
  }

  document.addEventListener("DOMContentLoaded", function () {
    // Restore saved theme (default: ocean)
    let saved = "ocean";
    try { saved = localStorage.getItem(STORAGE_KEY) || "ocean"; } catch (_) {}
    applyTheme(saved);

    // Wire up swatch buttons
    document.querySelectorAll(".swatch").forEach(function (btn) {
      btn.addEventListener("click", function () {
        applyTheme(btn.dataset.theme);
      });
    });
  });
})();
