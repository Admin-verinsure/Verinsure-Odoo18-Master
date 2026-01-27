(function () {
  "use strict";

  function collectAnswers(formEl) {
    const answers = {};
    const checkboxGroups = new Set();
    const radioGroups = new Set();

    formEl.querySelectorAll("[data-field-id]").forEach((el) => {
      const fid = el.dataset.fieldId;
      if (!fid) return;

      if (el.type === "checkbox") checkboxGroups.add(fid);
      if (el.type === "radio") radioGroups.add(fid);

      if (el.type === "checkbox") {
        if (!Array.isArray(answers[fid])) answers[fid] = [];
        if (el.checked) answers[fid].push(el.value);
      } else if (el.type === "radio") {
        if (el.checked) answers[fid] = el.value;
      } else if (el.tagName === "SELECT" && el.multiple) {
        answers[fid] = Array.from(el.selectedOptions).map((o) => o.value);
      } else {
        answers[fid] = el.value;
      }
    });

    // Ensure groups exist even when nothing selected
    checkboxGroups.forEach((fid) => {
      if (!answers[fid]) answers[fid] = [];
    });
    radioGroups.forEach((fid) => {
      if (answers[fid] === undefined) answers[fid] = "";
    });

    return answers;
  }

  async function getNextToken(formEl) {
    const token = formEl.querySelector("input[name='token']")?.value;
    if (!token) return null;

    const answers = collectAnswers(formEl);

    try {
      const res = await fetch(`/smart_form/branching/${token}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
        credentials: "same-origin",
      });
      if (!res.ok) return null;
      const data = await res.json();
      if (data && data.success && data.next_token) return data.next_token;
      return null;
    } catch (e) {
      return null;
    }
  }

  async function refreshContinueCTA(formEl) {
    const cta = document.getElementById("sfb-branching-cta");
    if (!cta) return;

    const nextToken = await getNextToken(formEl);
    if (!nextToken) {
      cta.innerHTML = "";
      return;
    }
    cta.innerHTML = `<a class="btn btn-outline-primary" href="/smart_form/${nextToken}">Continue</a>`;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const formEl =
      document.querySelector("form[action='/smart_form/submit']") ||
      document.querySelector("form");
    if (!formEl) return;

    // Live CTA preview (optional)
    refreshContinueCTA(formEl);
    formEl.addEventListener("change", () => refreshContinueCTA(formEl));

    // Core: branching redirect on submit
    formEl.addEventListener("submit", async (ev) => {
      // Only handle our public form
      const tokenInput = formEl.querySelector("input[name='token']");
      if (!tokenInput) return;

      // If user held meta/ctrl (open new tab), or form has explicit no-branching flag, don't intercept
      if (ev.metaKey || ev.ctrlKey || formEl.dataset.noBranching === "1") return;

      ev.preventDefault();
      const nextToken = await getNextToken(formEl);

      // If branching produced a next form, redirect instead of submitting
      if (nextToken) {
        window.location.href = `/smart_form/${nextToken}`;
        return;
      }

      // Otherwise, submit current form normally
      formEl.submit();
    });
  });
})();
