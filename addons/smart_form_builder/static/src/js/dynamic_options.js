(function () {
  "use strict";

  async function loadOptions(selectEl) {
    try {
      const fieldId = selectEl.dataset.fieldId;
      const token = selectEl.dataset.formToken;
      if (!fieldId) return;

      const url = `/smart_form/options/${encodeURIComponent(fieldId)}` + (token ? `?token=${encodeURIComponent(token)}` : "");
      const res = await fetch(url, { method: "GET", credentials: "same-origin" });
      if (!res.ok) return;

      const data = await res.json();
      if (!data || !data.success) return;

      const placeholder = selectEl.querySelector("option") ? selectEl.querySelector("option").cloneNode(true) : null;
      selectEl.innerHTML = "";
      if (placeholder) selectEl.appendChild(placeholder);

      (data.options || []).forEach((o) => {
        const opt = document.createElement("option");
        opt.value = o.value;
        opt.textContent = o.label;
        selectEl.appendChild(opt);
      });
    } catch (e) {
      // silent
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("select[data-dynamic-options='1']").forEach(loadOptions);
  });
})();
