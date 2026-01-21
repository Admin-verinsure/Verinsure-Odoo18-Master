(function () {
  "use strict";

  async function loadOptionsForSelect(selectEl) {
    try {
      if (selectEl.dataset.dynamicOptions !== "1") return;

      const fieldId = selectEl.dataset.fieldId;
      const token = selectEl.dataset.formToken;

      const url = token
        ? `/smooth_form/options/${encodeURIComponent(fieldId)}?token=${encodeURIComponent(token)}`
        : `/smooth_form/options/${encodeURIComponent(fieldId)}`;

      const res = await fetch(url, { method: "GET", credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      if (!data || !data.success) return;

      const firstOpt = selectEl.querySelector("option") || null;
      const placeholder = firstOpt ? { value: firstOpt.value, label: firstOpt.textContent } : null;

      selectEl.innerHTML = "";
      if (placeholder) {
        const opt = document.createElement("option");
        opt.value = placeholder.value;
        opt.textContent = placeholder.label;
        selectEl.appendChild(opt);
      }

      (data.options || []).forEach((o) => {
        const option = document.createElement("option");
        option.value = o.value;
        option.textContent = o.label;
        selectEl.appendChild(option);
      });
    } catch (e) {
      console.error("SmoothForm dynamic options error:", e);
    }
  }

  function collectAnswers(formEl) {
    const answers = {};
    formEl.querySelectorAll("[data-field-id]").forEach((el) => {
      const fid = el.dataset.fieldId;
      if (!fid) return;

      if (el.type === "checkbox") {
        answers[fid] = el.checked ? (el.value || "true") : "";
      } else if (el.type === "radio") {
        if (el.checked) answers[fid] = el.value;
      } else {
        answers[fid] = el.value || "";
      }
    });
    return answers;
  }

  async function evaluateBranching(formEl) {
    const tokenInput = formEl.querySelector('input[name="token"]');
    const token = tokenInput ? tokenInput.value : null;
    if (!token) return;

    try {
      const answers = collectAnswers(formEl);
      const res = await fetch(`/smooth_form/branch/${encodeURIComponent(token)}`, {
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
      cta.innerHTML = `<a class="btn btn-outline-primary" href="/smooth_form/${data.next_token}">Continue</a>`;
    } catch (e) {
      console.error("SmoothForm branching error:", e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("select[data-dynamic-options='1']").forEach(loadOptionsForSelect);

    const formEl = document.querySelector("form");
    if (formEl) {
      evaluateBranching(formEl);
      formEl.addEventListener("change", () => evaluateBranching(formEl));
    }
  });
})();
