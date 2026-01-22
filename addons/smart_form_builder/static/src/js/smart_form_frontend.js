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

  // ---------- Searchable dropdown ----------
  function enhanceSelect(selectEl) {
    if (selectEl.dataset.sfbEnhanced === "1") return;
    selectEl.dataset.sfbEnhanced = "1";

    const options = Array.from(selectEl.options).map((o) => ({
      value: o.value,
      label: o.textContent || "",
    }));

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

      const placeholder = options.find((o) => o.value === "") || { value: "", label: "-- Select --" };
      const phItem = createEl("div", { class: "sfb-dd-item sfb-dd-placeholder" }, placeholder.label);
      phItem.addEventListener("click", (e) => {
        e.preventDefault();
        selectEl.value = "";
        selectEl.dispatchEvent(new Event("change", { bubbles: true }));
        syncBtnLabel();
        close();
      });
      list.appendChild(phItem);

      let count = 0;
      for (const opt of options) {
        if (opt.value === "") continue;
        if (q && !opt.label.toLowerCase().includes(q)) continue;

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
        count++;
      }

      if (count === 0) {
        list.appendChild(createEl("div", { class: "sfb-dd-empty" }, "No results"));
      }
    }

    function open() {
      panel.classList.remove("d-none");
      renderList(search.value);
      setTimeout(() => {
        search.focus();
        const v = search.value;
        search.setSelectionRange(v.length, v.length);
      }, 0);
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

    // prevent outside-close while typing
    ["click","mousedown","mouseup","keydown","keyup","keypress"].forEach((evt) => {
      search.addEventListener(evt, (e) => e.stopPropagation());
      panel.addEventListener(evt, (e) => e.stopPropagation());
      wrap.addEventListener(evt, (e) => e.stopPropagation());
    });

    search.addEventListener("input", () => {
      const cur = search.value;
      renderList(cur);
      setTimeout(() => {
        search.focus();
        search.setSelectionRange(cur.length, cur.length);
      }, 0);
    });

    document.addEventListener("click", () => close());

    panel.appendChild(header);
    panel.appendChild(list);
    wrap.appendChild(btn);
    wrap.appendChild(panel);
    selectEl.parentNode.insertBefore(wrap, selectEl.nextSibling);

    syncBtnLabel();
  }

  function initDropdowns() {
    document.querySelectorAll("select.sfb-enhanced-select").forEach(enhanceSelect);
  }

  // ---------- Branching ----------
  function collectAnswers(formEl) {
    const answers = {};
    formEl.querySelectorAll("[data-field-id]").forEach((el) => {
      const fid = el.getAttribute("data-field-id");
      if (!fid) return;

      if (el.type === "radio") {
        if (el.checked) answers[fid] = el.value || "";
        return;
      }
      if (el.type === "checkbox") {
        if (!answers[fid]) answers[fid] = [];
        if (el.checked) answers[fid].push(el.value || "true");
        return;
      }
      if (el.tagName === "SELECT") {
        const idx = el.selectedIndex;
        const label = idx >= 0 && el.options[idx] ? (el.options[idx].textContent || "") : "";
        answers[fid] = { value: el.value || "", label: label.trim() };
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
      const res = await fetch(`/smart_form/branching/${encodeURIComponent(token)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ answers: collectAnswers(formEl) }),
        credentials: "same-origin",
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.success && data.next_token) {
        window.location.href = `/smart_form/${data.next_token}`;
      }
    } catch (e) {}
  }

  function initBranching() {
    const formEl = document.querySelector("form#smart-form") || document.querySelector("form[action='/smart_form/submit']");
    if (!formEl) return;
    formEl.addEventListener("change", () => evaluateBranching(formEl));
  }

  document.addEventListener("DOMContentLoaded", () => {
    initDropdowns();
    initBranching();
    setTimeout(initDropdowns, 500);
  });
})();