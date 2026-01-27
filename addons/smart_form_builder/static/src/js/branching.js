(function () {
  "use strict";

  // rules_json is already rendered by backend
  const RULES = window.SFB_RULES || [];
  let nextFormToken = null;

  function collectAnswers(formEl) {
    const answers = {};
    formEl.querySelectorAll("[data-field-id]").forEach((el) => {
      const fid = el.dataset.fieldId;
      if (!fid) return;

      if (el.type === "checkbox") {
        if (!answers[fid]) answers[fid] = [];
        if (el.checked) answers[fid].push(el.value || "true");
      } else if (el.type === "radio") {
        if (el.checked) answers[fid] = el.value;
      } else {
        answers[fid] = el.value || "";
      }
    });
    return answers;
  }

  function normalize(val) {
    if (Array.isArray(val)) return val.map((v) => String(v).toLowerCase());
    return [String(val || "").toLowerCase()];
  }

  function match(rule, value) {
    const vals = normalize(value);
    const want = (rule.value || "").toLowerCase();

    if (rule.op === "in") {
      return vals.includes(want);
    }
    if (rule.op === "contains") {
      return vals.some((v) => v.includes(want));
    }
    if (rule.op === "!=") {
      return vals.every((v) => v !== want);
    }
    return vals.includes(want); // default "="
  }

  function evaluateBranching(formEl) {
    nextFormToken = null;
    const answers = collectAnswers(formEl);

    for (const rule of RULES) {
      const key = String(rule.trigger);
      if (!(key in answers)) continue;

      if (match(rule, answers[key])) {
        nextFormToken = rule.target_token || null;
        break;
      }
    }

    // Optional CTA preview (like field logic preview)
    const cta = document.getElementById("sfb-branching-cta");
    if (cta) {
      if (nextFormToken) {
        cta.innerHTML = `<a class="btn btn-outline-primary" href="/smart_form/${nextFormToken}">Continue</a>`;
      } else {
        cta.innerHTML = "";
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const formEl = document.querySelector("form");
    if (!formEl) return;

    // Evaluate on change (JUST LIKE FIELD LOGIC)
    formEl.addEventListener("change", () => evaluateBranching(formEl));

    // Final decision on submit
    formEl.addEventListener("submit", (e) => {
      if (nextFormToken) {
        e.preventDefault();
        window.location.href = `/smart_form/${nextFormToken}`;
      }
    });
  });

  console.log("✅ Branching logic loaded (field-logic style)");
})();
