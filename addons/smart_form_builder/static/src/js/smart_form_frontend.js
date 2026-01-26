(function () {
  "use strict";

  function parseRules() {
    const el = document.getElementById("sfb-rules-json");
    if (!el) return [];
    try {
      const txt = (el.textContent || "[]").trim();
      return JSON.parse(txt || "[]") || [];
    } catch (e) {
      return [];
    }
  }

  // Keep existing dropdown enhancement if you have another file; here we only ensure no syntax errors.
})();