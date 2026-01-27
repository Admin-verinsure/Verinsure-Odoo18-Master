(function () {
  "use strict";

  // ---------------------------------------------
  // COLLECT ANSWERS
  // ---------------------------------------------
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

  // ---------------------------------------------
  // CALL BRANCHING API
  // ---------------------------------------------
  async function callBranching(formEl) {
    const tokenInput = formEl.querySelector('input[name="token"]');
    if (!tokenInput) return null;

    try {
      const res = await fetch(
        `/smart_form/branching/${encodeURIComponent(tokenInput.value)}`,
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
      console.error("❌ Branching request failed", e);
      return null;
    }
  }

  // ---------------------------------------------
  // CTA PREVIEW (OPTIONAL)
  // ---------------------------------------------
  async function updateCTA(formEl) {
    const cta = document.getElementById("sfb-branching-cta");
    if (!cta) return;

    const data = await callBranching(formEl);

    if (data && data.success && data.next_token) {
      cta.innerHTML = `
        <a class="btn btn-outline-primary" href="/smart_form/${data.next_token}">
          Continue
        </a>`;
    } else {
      cta.innerHTML = "";
    }
  }

  // ---------------------------------------------
  // SUBMIT HANDLER (FINAL AUTHORITY)
  // ---------------------------------------------
  async function onSubmit(ev) {
    const formEl = ev.target;
    if (!(formEl instanceof HTMLFormElement)) return;

    const tokenInput = formEl.querySelector('input[name="token"]');
    if (!tokenInput) return;

    ev.preventDefault(); // 🔥 intercept once

    const data = await callBranching(formEl);

    // 🔁 Branch exists → redirect
    if (data && data.success && data.next_token) {
      window.location.href = `/smart_form/${data.next_token}`;
      return;
    }

    // ✅ Terminal form → submit ONCE
    document.removeEventListener("submit", onSubmit, true);
    formEl.submit();
  }

  // ---------------------------------------------
  // INIT
  // ---------------------------------------------
  document.addEventListener("DOMContentLoaded", () => {
    const formEl =
      document.querySelector("form[action='/smart_form/submit']") ||
      document.querySelector("form");

    if (!formEl) return;

    updateCTA(formEl);
    formEl.addEventListener("change", () => updateCTA(formEl));
  });

  // 🔥 CAPTURE PHASE SUBMIT INTERCEPT
  document.addEventListener("submit", onSubmit, true);

  console.log("✅ Smart Form Branching JS ACTIVE");
})();
