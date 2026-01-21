/** Branching: when answers change, ask server for next form token and show a link/button */
(function () {
  "use strict";

  function collectAnswers(formEl) {
    const answers = {};

    formEl.querySelectorAll("[data-field-id]").forEach((el) => {
      const fid = el.dataset.fieldId;
      if (!fid) return;

      if (el.type === "checkbox") {
        answers[fid] = el.checked ? el.value || "true" : "";
      } else if (el.type === "radio") {
        if (el.checked) answers[fid] = el.value;
      } else if (el.tagName === "SELECT") {
        answers[fid] = el.value || "";
      } else {
        answers[fid] = el.value || "";
      }
    });

    return answers;
  }

  function ensureCta(formEl) {
    let cta = formEl.querySelector("#dfb-branching-cta");
    if (!cta) {
      cta = document.createElement("div");
      cta.id = "dfb-branching-cta";
      cta.style.marginTop = "12px";
      cta.style.textAlign = "center";
      formEl.appendChild(cta);
    }
    return cta;
  }

  async function evaluateBranching(formEl) {
    // Zehntech form uses hidden input name="token" for shared form token
    const tokenInput = formEl.querySelector('input[name="token"]');
    const token = tokenInput ? tokenInput.value : null;
    if (!token) return;

    const answers = collectAnswers(formEl);

    try {
      const res = await fetch(
        `/form_builder/branching/${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answers }),
          credentials: "same-origin",
        },
      );

      if (!res.ok) return;

      const data = await res.json();
      const cta = ensureCta(formEl);

      if (!data || !data.success || !data.next_token) {
        cta.innerHTML = "";
        return;
      }

      const url = `/form_builder/shared/${data.next_token}`;
      cta.innerHTML = `<a class="btn btn-primary" href="${url}">Continue</a>`;
    } catch (e) {
      // console.error("branching eval failed", e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const formEl =
      document.querySelector('form[action="/form_builder/submit"]') ||
      document.querySelector("form");

    if (!formEl) return;

    // Evaluate once and on any change
    evaluateBranching(formEl);
    formEl.addEventListener("change", () => evaluateBranching(formEl));
  });
})();
