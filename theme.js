/* Light / dark mode switch.
   - Uses the visitor's saved choice (localStorage) if there is one,
   - otherwise follows the device setting (prefers-color-scheme). */
(function () {
  var KEY = "brightmart-theme";
  var root = document.documentElement;

  function systemTheme() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function saved() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }
  function apply(theme) { root.setAttribute("data-theme", theme); }

  apply(saved() || systemTheme());           // runs before the page paints (no flash)

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      apply(next);
      try { localStorage.setItem(KEY, next); } catch (e) { /* storage blocked: still works for this visit */ }
    });
  });
})();
