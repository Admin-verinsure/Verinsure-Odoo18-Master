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

  // 🔥 GLOBAL SUBMIT INTERCEPT (CAPTURE PHASE — CRITICAL)
  document.addEventListener(
    "submit",
    async function (ev) {
      const formEl = ev.target;
      if (!(formEl instanceof HTMLFormElement)) return;

      // Only intercept smart forms
      if (
        !formEl.dataset.formToken &&
        !formEl.querySelector('input[name="token"]')
      ) {
        return;
      }

      ev.preventDefault();
      ev.stopImmediatePropagation();

      const data = await evaluateBranching(formEl);

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

      // 🔁 No branching → allow real submit
      formEl.removeAttribute("data-branching-lock");
      formEl.submit();
    },
    true, // 🔥 CAPTURE PHASE (THIS IS WHY IT WORKS)
  );

  console.log("✅ Smart Form Branching ACTIVE");
})();
