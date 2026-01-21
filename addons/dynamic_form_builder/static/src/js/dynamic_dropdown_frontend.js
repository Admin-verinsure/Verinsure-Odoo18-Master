/** Dynamic dropdown loader for public forms (zehntech_form_builder extension) */
(function () {
  "use strict";

  async function loadOptionsForSelect(selectEl) {
    try {
      const fieldId = selectEl.dataset.fieldId;
      const token = selectEl.dataset.formToken;

      if (!fieldId) return;

      const url = token
        ? `/form_builder/dynamic_options/${encodeURIComponent(fieldId)}?token=${encodeURIComponent(token)}`
        : `/form_builder/dynamic_options/${encodeURIComponent(fieldId)}`;

      const res = await fetch(url, {
        method: "GET",
        credentials: "same-origin",
      });
      if (!res.ok) {
        // console.error("dynamic_options http error", res.status);
        return;
      }

      const data = await res.json();
      if (!data || !data.success) return;

      // Keep first option as placeholder (usually "-- Select --")
      const firstOpt = selectEl.querySelector("option") || null;
      const placeholder = firstOpt
        ? { value: firstOpt.value, label: firstOpt.textContent }
        : null;

      // Clear existing options
      selectEl.innerHTML = "";

      // Restore placeholder
      if (placeholder) {
        const opt = document.createElement("option");
        opt.value = placeholder.value;
        opt.textContent = placeholder.label;
        selectEl.appendChild(opt);
      }

      // Append fetched options
      (data.options || []).forEach((o) => {
        const option = document.createElement("option");
        option.value = o.value;
        option.textContent = o.label;
        selectEl.appendChild(option);
      });
    } catch (e) {
      // fail silently on public pages
      // console.error("dynamic options load failed", e);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document
      .querySelectorAll('select[data-dynamic-options="1"]')
      .forEach((el) => {
        loadOptionsForSelect(el);
      });
  });
})();
