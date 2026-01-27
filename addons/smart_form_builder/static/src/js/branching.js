(function () {
  "use strict";

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
        if (el.checked) answers[fid] = el.value || "";
      } else {
        answers[fid] = el.value || "";
      }
    });
    return answers;
  }

  async function evaluateBranching(formEl) {
    const tokenEl = formEl.querySelector('input[name="token"]');
    if (!tokenEl) return;

    try {
      const res = await fetch(
        `/smart_form/branching/${encodeURIComponent(tokenEl.value)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answers: collectAnswers(formEl) }),
          credentials: "same-origin",
        },
      );

      if (!res.ok) return;

      const data = await res.json();
      nextFormToken = data && data.success ? data.next_token : null;

      // Optional preview CTA
      const cta = document.getElementById("sfb-branching-cta");
      if (cta) {
        cta.innerHTML = nextFormToken
          ? `<a class="btn btn-outline-primary" href="/smart_form/${nextFormToken}">Continue</a>`
          : "";
      }
    } catch (e) {
      console.error("Branching evaluation failed", e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const formEl = document.getElementById("smart-form");
    if (!formEl) return;

    // Evaluate like field logic
    formEl.addEventListener("input", () => evaluateBranching(formEl));
    formEl.addEventListener("change", () => evaluateBranching(formEl));

    // Continue button only (NO submit hijack)
    const btn = document.getElementById("sfb-continue");
    if (btn) {
      btn.addEventListener("click", () => {
        if (nextFormToken) {
          window.location.href = `/smart_form/${nextFormToken}`;
        }
      });
    }
  });

  console.log("✅ Branching logic loaded (backend-evaluated)");
})();
