(function () {
  "use strict";

  function createEl(tag, attrs, text) {
    const el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach((k) => {
        if (k === "class") el.className = attrs[k];
        else el.setAttribute(k, attrs[k]);
      });
    }
    if (text !== undefined && text !== null) el.textContent = text;
    return el;
  }

  function enhanceSelect(selectEl) {
    if (selectEl.dataset.sfbEnhanced === "1") return;
    selectEl.dataset.sfbEnhanced = "1";

    const options = Array.from(selectEl.options).map((o) => ({
      value: o.value,
      label: o.textContent || "",
      disabled: o.disabled,
    }));

    selectEl.style.display = "none";

    const wrap = createEl("div", { class: "sfb-dd" });
    const btn = createEl("button", { type: "button", class: "form-select sfb-dd-btn" });
    const panel = createEl("div", { class: "sfb-dd-panel d-none" });
    const search = createEl("input", {
      type: "text",
      class: "form-control sfb-dd-search",
      placeholder: "Search...",
    });
    const list = createEl("div", { class: "sfb-dd-list" });

    function syncBtnLabel() {
      const cur = selectEl.value;
      const found = options.find((x) => x.value === cur);
      btn.textContent = found ? found.label : (options[0] ? options[0].label : "-- Select --");
    }

    function renderList(filter) {
      const q = (filter || "").toLowerCase().trim();
      list.innerHTML = "";

      options.forEach((opt, idx) => {
        // placeholder always at top
        if (idx === 0) {
          const item = createEl("div", { class: "sfb-dd-item sfb-dd-placeholder" }, opt.label);
          item.addEventListener("click", () => {
            selectEl.value = opt.value;
            selectEl.dispatchEvent(new Event("change", { bubbles: true }));
            syncBtnLabel();
            close();
          });
          list.appendChild(item);
          return;
        }

        if (q && !opt.label.toLowerCase().includes(q)) return;

        const item = createEl("div", { class: "sfb-dd-item" }, opt.label);
        if (opt.value === selectEl.value) item.classList.add("active");
        item.addEventListener("click", () => {
          selectEl.value = opt.value;
          selectEl.dispatchEvent(new Event("change", { bubbles: true }));
          syncBtnLabel();
          close();
        });
        list.appendChild(item);
      });

      if (!list.childElementCount) {
        list.appendChild(createEl("div", { class: "sfb-dd-empty" }, "No results"));
      }
    }

    function open() {
      panel.classList.remove("d-none");
      renderList(search.value);
      setTimeout(() => search.focus(), 0);
    }
    function close() {
      panel.classList.add("d-none");
    }

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (panel.classList.contains("d-none")) open();
      else close();
    });

    search.addEventListener("input", () => renderList(search.value));

    document.addEventListener("click", (e) => {
      if (!wrap.contains(e.target)) close();
    });

    panel.appendChild(search);
    panel.appendChild(list);
    wrap.appendChild(btn);
    wrap.appendChild(panel);

    selectEl.parentNode.insertBefore(wrap, selectEl.nextSibling);
    syncBtnLabel();
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("select.sfb-enhanced-select").forEach(enhanceSelect);
  });
})();