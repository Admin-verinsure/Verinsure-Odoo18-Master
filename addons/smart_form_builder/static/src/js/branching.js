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

  async function callBranching(formEl) {
    const tokenInput = formEl.querySelector('input[name="token"]');
    const token = tokenInput ? tokenInput.value : null;
    if (!token) return null;

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
      console.error("Branching call failed", e);
      return null;
    }
  }

  // ---------------------------------------------
  // LIVE PREVIEW (KEEPING YOUR EXISTING FEATURE)
  // ---------------------------------------------
  async function updateCTA(formEl) {
    const data = await callBranching(formEl);
    const cta = document.getElementById("sfb-branching-cta");
    if (!cta) return;

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
  // SUBMIT INTERCEPT (THIS IS THE FIX)
  // ---------------------------------------------
  document.addEventListener(
    "submit",
    async function (ev) {
      const formEl = ev.target;
      if (!(formEl instanceof HTMLFormElement)) return;

      const tokenInput = formEl.querySelector('input[name="token"]');
      if (!tokenInput) return;

      ev.preventDefault(); // 🔥 CRITICAL

      const data = await callBranching(formEl);

      if (data && data.success && data.next_token) {
        // 🔁 Branch or fallback exists → redirect
        window.location.href = `/smart_form/${data.next_token}`;
        return;
      }

      // ✅ Terminal form → allow actual submit
      formEl.removeEventListener("submit", arguments.callee, true);
      formEl.submit();
    },
    true, // 🔥 CAPTURE PHASE (VERY IMPORTANT)
  );

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

  console.log("✅ Smart Form Branching JS loaded");
})();
