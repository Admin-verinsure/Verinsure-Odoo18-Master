(function () {
  "use strict";

  const BRANCHING_LOCK = "__sfb_branching_done__";

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
      } else if (el.value !== "" && el.value !== null) {
        answers[fid] = el.value;
      }
    });

    return answers;
  }

  async function evaluateBranching(formEl) {
    const token =
      formEl.dataset.formToken ||
      (formEl.querySelector('input[name="token"]') || {}).value ||
      null;

    if (!token) {
      console.error("❌ Branching token missing");
      return null;
    }

    try {
      const res = await fetch(
        `/smart_form/branching/${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answers: collectAnswers(formEl) }),
          credentials: "same-origin",
        },
      );

      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      console.error("❌ Branching fetch failed", e);
      return null;
    }
  }

  // 🔥 GLOBAL SUBMIT INTERCEPT (CAPTURE PHASE)
  document.addEventListener(
    "submit",
    async function (ev) {
      const formEl = ev.target;
      if (!(formEl instanceof HTMLFormElement)) return;

      // Already processed → allow normal submit
      if (formEl[BRANCHING_LOCK]) return;

      // Only smart forms
      if (
        !formEl.dataset.formToken &&
        !formEl.querySelector('input[name="token"]')
      ) {
        return;
      }

      ev.preventDefault();
      ev.stopImmediatePropagation();

      const data = await evaluateBranching(formEl);

      // 🔀 Redirect if branching matched
      if (data && data.success) {
        if (data.next_token) {
          window.location.href = `/smart_form/${data.next_token}`;
          return;
        }
        if (data.fallback_token) {
          window.location.href = `/smart_form/${data.fallback_token}`;
          return;
        }
      }

      // 🔓 No branching → allow natural submit ONCE
      formEl[BRANCHING_LOCK] = true;
      formEl.dispatchEvent(new Event("submit", { bubbles: true }));
    },
    true, // capture phase
  );

  console.log("✅ Smart Form Branching ACTIVE");
})();
