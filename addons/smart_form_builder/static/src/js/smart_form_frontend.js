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

    // Hide native select but keep it for form submission
    selectEl.style.display = "none";

    const wrap = createEl("div", { class: "sfb-dd" });
    const btn = createEl("button", { type: "button", class: "form-select sfb-dd-btn" });
    const panel = createEl("div", { class: "sfb-dd-panel d-none" });

    const header = createEl("div", { class: "sfb-dd-header" });
    const search = createEl("input", {
      type: "text",
      class: "form-control sfb-dd-search",
      placeholder: "Search...",
      autocomplete: "off",
    });
    header.appendChild(search);

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
        // placeholder always at top (idx 0)
        if (idx === 0) {
          const item = createEl("div", { class: "sfb-dd-item sfb-dd-placeholder" }, opt.label);
          item.addEventListener("click", (e) => {
            e.preventDefault();
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

        item.addEventListener("click", (e) => {
          e.preventDefault();
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
      search.value = "";
      renderList("");
      setTimeout(() => search.focus(), 0);
    }

    function close() {
      panel.classList.add("d-none");
    }

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (panel.classList.contains("d-none")) open();
      else close();
    });

    search.addEventListener("click", (e) => e.stopPropagation());
    search.addEventListener("input", () => renderList(search.value));

    // Prevent outside close when clicking inside panel
    panel.addEventListener("click", (e) => e.stopPropagation());
    wrap.addEventListener("click", (e) => e.stopPropagation());

    document.addEventListener("click", () => close());

    panel.appendChild(header);
    panel.appendChild(list);
    wrap.appendChild(btn);
    wrap.appendChild(panel);
    selectEl.parentNode.insertBefore(wrap, selectEl.nextSibling);

    syncBtnLabel();
  }

  function init() {
    document.querySelectorAll("select.sfb-enhanced-select").forEach(enhanceSelect);
  }

  document.addEventListener("DOMContentLoaded", () => {
    init();
    // In case the page is partially re-rendered by website editor, try again shortly
    setTimeout(init, 500);
  });
})();