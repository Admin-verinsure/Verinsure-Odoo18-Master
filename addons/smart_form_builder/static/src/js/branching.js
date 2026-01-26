(function () {
  "use strict";

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
        if (el.value !== "" && el.value !== null) {
        answers[fid] = el.value;
      }
      }
    });
    return answers;
  }

  async function evaluateBranching(formEl) {
    const tokenInput = formEl.querySelector('input[name="token"]');
    const token = tokenInput ? tokenInput.value : null;
    if (!token) return;

    const answers = collectAnswers(formEl);
    try {
      const res = await fetch(`/smart_form/branching/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
        credentials: "same-origin",
      });
      if (!res.ok) return;
      const data = await res.json();
      const cta = document.getElementById("sfb-branching-cta");
      if (!cta) return;

      if (!data || !data.success || !data.next_token) {
        cta.innerHTML = "";
        return;
      }
      cta.innerHTML = `<a class="btn btn-outline-primary" href="/smart_form/${data.next_token}">Continue</a>`;
    } catch (e) {
      // silent
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const formEl = document.querySelector("form[action='/smart_form/submit']") || document.querySelector("form");
    if (!formEl) return;
    evaluateBranching(formEl);
    formEl.addEventListener("change", () => evaluateBranching(formEl));
  });
})();
