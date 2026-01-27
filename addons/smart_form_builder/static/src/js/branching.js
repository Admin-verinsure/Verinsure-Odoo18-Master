(function () {
  "use strict";

  function collectAnswers(formEl) {
    const answers = {};
    const seenRadio = new Set();
    const seenCheckbox = new Set();

    // Collect values
    formEl.querySelectorAll("[data-field-id]").forEach((el) => {
      const fid = el.dataset.fieldId;
      if (!fid) return;

      const tag = (el.tagName || "").toLowerCase();
      const type = (el.type || "").toLowerCase();

      if (type === "checkbox") {
        seenCheckbox.add(fid);
        if (!answers[fid]) answers[fid] = [];
        if (el.checked) answers[fid].push(el.value || "true");
        return;
      }

      if (type === "radio") {
        seenRadio.add(fid);
        if (el.checked) {
          answers[fid] = el.value;
        }
        return;
      }

      if (tag === "select") {
        const value = el.value || "";
        const label = el.selectedOptions && el.selectedOptions[0] ? (el.selectedOptions[0].textContent || "").trim() : "";
        answers[fid] = { value, label };
        return;
      }

      // default inputs/textarea
      answers[fid] = el.value != null ? String(el.value) : "";
    });

    // Ensure missing radios/checkboxes still appear so backend can evaluate != rules
    seenRadio.forEach((fid) => {
      if (!(fid in answers)) answers[fid] = "";
    });
    seenCheckbox.forEach((fid) => {
      if (!(fid in answers)) answers[fid] = [];
    });

    return answers;
  }

  async function evaluateBranching(formEl) {
    const tokenInput = formEl.querySelector('input[name="token"]');
    const token = tokenInput ? tokenInput.value : null;
    if (!token) return null;

    const answers = collectAnswers(formEl);

    try {
      const res = await fetch(`/smart_form/branching/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers }),
        credentials: "same-origin",
      });
      if (!res.ok) return null;
      const data = await res.json();
      if (!data || !data.success) return null;
      return data.next_token || null;
    } catch (e) {
      return null;
    }
  }

  function init() {
    const formEl = document.getElementById("smart-form");
    if (!formEl) return;

    // Evaluate on change to update optional CTA if it exists
    const maybeUpdateCTA = async () => {
      const nextToken = await evaluateBranching(formEl);
      const cta = document.getElementById("sfb-branching-cta");
      if (!cta) return;
      if (nextToken) {
        cta.style.display = "";
        cta.setAttribute("href", `/smart_form/${encodeURIComponent(nextToken)}`);
      } else {
        cta.style.display = "none";
        cta.removeAttribute("href");
      }
    };

    formEl.addEventListener("change", () => {
      maybeUpdateCTA();
    });

    // Optional: intercept submit for client-side redirect (server-side also handles it)
    formEl.addEventListener("submit", async (ev) => {
      const nextToken = await evaluateBranching(formEl);
      if (nextToken) {
        ev.preventDefault();
        window.location.href = `/smart_form/${encodeURIComponent(nextToken)}`;
      }
    });

    maybeUpdateCTA();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
