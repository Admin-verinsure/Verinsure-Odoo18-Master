(function () {
  "use strict";

  async function populateDynamicSelect(sel) {
    try {
      const source = sel.dataset.optionSource;
      if (source !== "model") return;

      const fieldId = sel.dataset.fieldId;
      const token = sel.dataset.formToken;
      if (!fieldId || !token) return;

      const url = `/smart_form/options/${encodeURIComponent(fieldId)}?token=${encodeURIComponent(token)}`;
      const res = await fetch(url, { method: "GET", credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      if (!data || !data.success) return;

      // Preserve placeholder
      const placeholder = sel.querySelector("option") ? sel.querySelector("option").cloneNode(true) : null;
      sel.innerHTML = "";
      if (placeholder) sel.appendChild(placeholder);

      (data.options || []).forEach((o) => {
        const opt = document.createElement("option");
        opt.value = o.value;
        opt.textContent = o.label;
        sel.appendChild(opt);
      });
    } catch (e) {
      // silent
      // console.error(e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("select[data-option-source='model']").forEach(populateDynamicSelect);
  });
})();
