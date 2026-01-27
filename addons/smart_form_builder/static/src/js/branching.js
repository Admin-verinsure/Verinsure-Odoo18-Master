(function () {
  "use strict";

  let nextFormToken = null;
  let pending = false;

  // ---------------------------------------------
  // CHECK IF BRANCHING EXISTS
  // ---------------------------------------------
  function hasBranching() {
    const el = document.getElementById("sfb-has-branching");
    return el && el.value === "1";
  }

  // ---------------------------------------------
  // COLLECT ANSWERS (MATCHES BACKEND EXPECTATION)
  // ---------------------------------------------
  function collectAnswers(formEl) {
    const answers = {};

    formEl
      .querySelectorAll(
        "input[data-field-id], select[data-field-id], textarea[data-field-id]",
      )
      .forEach((el) => {
        const fid = el.dataset.fieldId;
        if (!fid) return;

        if (el.type === "radio") {
          if (el.checked) {
            answers[fid] = el.value || "";
          }
          return;
        }

        if (el.type === "checkbox") {
          if (!answers[fid]) answers[fid] = [];
          if (el.checked) {
            answers[fid].push(el.value || "true");
          }
          return;
        }

        answers[fid] = el.value || "";
      });

    return answers;
  }

  // ---------------------------------------------
  // CALL BACKEND BRANCHING
  // ---------------------------------------------
  async function evaluateBranching(formEl) {
    if (!hasBranching() || pending) return;

    const tokenEl = formEl.querySelector('input[name="token"]');
    if (!tokenEl) return;

    pending = true;
    nextFormToken = null;

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
      nextFormToken =
        data && data.success && data.next_token ? data.next_token : null;

      // Optional preview CTA
      const cta = document.getElementById("sfb-branching-cta");
      if (cta) {
        cta.innerHTML = nextFormToken
          ? `<a class="btn btn-outline-primary" href="/smart_form/${nextFormToken}">Continue</a>`
          : "";
      }
    } catch (e) {
      console.error("Branching evaluation failed", e);
    } finally {
      pending = false;
    }
  }

  // ---------------------------------------------
  // INIT
  // ---------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const formEl = document.getElementById("smart-form");
    if (!formEl) return;

    // No branching → behave like normal form
    if (!hasBranching()) return;

    // Re-evaluate like field logic
    formEl.addEventListener("input", () => evaluateBranching(formEl));
    formEl.addEventListener("change", () => evaluateBranching(formEl));

    // Continue button
    const btn = document.getElementById("sfb-continue");
    if (!btn) return;

    btn.addEventListener("click", () => {
      if (nextFormToken) {
        window.location.href = `/smart_form/${nextFormToken}`;
      } else {
        // ✅ NO MATCH + NO FALLBACK → NORMAL SUBMIT
        formEl.submit();
      }
    });
  });

  console.log("✅ Branching JS loaded (final, stable)");
})();
