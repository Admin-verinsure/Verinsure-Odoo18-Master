(function () {
  "use strict";

  let nextFormToken = null;
  let pending = false; // prevent request flooding

  // --------------------------------------------------
  // COLLECT ANSWERS (SAFE + CLEAN)
  // --------------------------------------------------
  function collectAnswers(formEl) {
    const answers = {};

    formEl
      .querySelectorAll(
        "input[data-field-id], select[data-field-id], textarea[data-field-id]",
      )
      .forEach((el) => {
        const fid = el.dataset.fieldId;
        if (!fid) return;

        // RADIO
        if (el.type === "radio") {
          if (el.checked) {
            answers[fid] = el.value || "";
          }
          return;
        }

        // CHECKBOX
        if (el.type === "checkbox") {
          if (!answers[fid]) answers[fid] = [];
          if (el.checked) {
            answers[fid].push(el.value || "true");
          }
          return;
        }

        // OTHER INPUTS
        answers[fid] = el.value || "";
      });

    return answers;
  }

  // --------------------------------------------------
  // CALL BACKEND BRANCHING (AUTHORITATIVE)
  // --------------------------------------------------
  async function evaluateBranching(formEl) {
    if (pending) return;

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

      if (data && data.success && data.next_token) {
        nextFormToken = data.next_token;
      } else {
        nextFormToken = null;
      }

      // OPTIONAL PREVIEW CTA
      const cta = document.getElementById("sfb-branching-cta");
      if (cta) {
        cta.innerHTML = nextFormToken
          ? `<a class="btn btn-outline-primary" href="/smart_form/${nextFormToken}">Continue</a>`
          : "";
      }
    } catch (e) {
      console.error("❌ Branching evaluation failed", e);
    } finally {
      pending = false;
    }
  }

  // --------------------------------------------------
  // INIT
  // --------------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const formEl = document.getElementById("smart-form");
    if (!formEl) return;

    // 🔁 Evaluate only on meaningful changes
    formEl.addEventListener("change", () => evaluateBranching(formEl));

    // 🚀 CONTINUE BUTTON (NO SUBMIT HIJACK)
    const btn = document.getElementById("sfb-continue");
    if (btn) {
      btn.addEventListener("click", () => {
        if (nextFormToken) {
          window.location.href = `/smart_form/${nextFormToken}`;
        } else {
          alert("No matching branch rule. Please review your inputs.");
        }
      });
    }
  });

  console.log("✅ Branching JS loaded (backend-evaluated, safe)");
})();
