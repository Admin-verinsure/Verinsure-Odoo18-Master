(function () {
  "use strict";

  function normalize(s) {
    return (s || "").toString().toLowerCase().trim();
  }

  function attachSearch(inputEl) {
    const targetSel = inputEl.getAttribute("data-target");
    if (!targetSel) return;
    const selectEl = document.querySelector(targetSel);
    if (!selectEl) return;

    const original = Array.from(selectEl.options).map((opt) => ({
      value: opt.value,
      label: opt.textContent || "",
    }));

    inputEl.addEventListener("input", () => {
      const q = normalize(inputEl.value);

      selectEl.innerHTML = "";

      // placeholder first
      const ph = original.find((o) => o.value === "");
      if (ph) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = ph.label;
        selectEl.appendChild(opt);
      }

      original.forEach((o) => {
        if (o.value === "") return;
        if (!q || normalize(o.label).includes(q)) {
          const opt = document.createElement("option");
          opt.value = o.value;
          opt.textContent = o.label;
          selectEl.appendChild(opt);
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".sfb-select-search").forEach(attachSearch);
  });
})();