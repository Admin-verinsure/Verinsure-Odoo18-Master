(function () {
  "use strict";

  function getRules() {
    const el = document.getElementById("sfb-rules-json");
    if (!el) return [];
    try {
      return JSON.parse(el.textContent || "[]") || [];
    } catch (e) {
      console.error("Field logic JSON error", e);
      return [];
    }
  }

  function inputs(fid) {
    return document.querySelectorAll(
      'input[data-field-id="' +
        fid +
        '"],select[data-field-id="' +
        fid +
        '"],textarea[data-field-id="' +
        fid +
        '"]',
    );
  }

  function wrapper(fid) {
    return document.querySelector('.sfb-field[data-field-id="' + fid + '"]');
  }

  function valueOf(fid) {
    const els = inputs(fid);
    if (!els.length) return "";

    const el = els[0];

    if (el.type === "radio") {
      for (let i = 0; i < els.length; i++) {
        if (els[i].checked) return els[i].value || "";
      }
      return "";
    }

    if (el.type === "checkbox") {
      const v = [];
      els.forEach((e) => {
        if (e.checked) v.push(e.value || "true");
      });
      return v;
    }

    return el.value || "";
  }

  function match(op, left, right) {
    const want = String(right || "").toLowerCase();
    const vals = Array.isArray(left) ? left : [left];
    const norm = vals.map((v) => String(v || "").toLowerCase());

    if (op === "contains" || op === "ilike") {
      return norm.some((v) => v.includes(want));
    }

    if (op === "!=") {
      return norm.every((v) => v !== want);
    }

    if (op === "in") {
      return want.split(",").some((w) => norm.includes(w.trim()));
    }

    return norm.includes(want);
  }

  function applyLogic(rules) {
    rules.forEach((r) => {
      const ok = match(r.op, valueOf(r.trigger), r.value);
      const w = wrapper(r.target);
      if (!w) return;

      if (r.action === "show") {
        w.style.display = ok ? "" : "none";
      }
      if (r.action === "hide") {
        w.style.display = ok ? "none" : "";
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const rules = getRules();
    if (!rules.length) return;

    // hide all "show" targets initially
    rules.forEach((r) => {
      if (r.action === "show") {
        const w = wrapper(r.target);
        if (w) w.style.display = "none";
      }
    });

    const form = document.getElementById("smart-form");
    if (!form) return;

    form.addEventListener("change", () => applyLogic(rules), true);
    form.addEventListener("input", () => applyLogic(rules), true);

    applyLogic(rules);
  });
})();
