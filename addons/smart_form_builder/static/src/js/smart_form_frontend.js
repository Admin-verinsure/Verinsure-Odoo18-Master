(function () {
  "use strict";

  // ---------- Conditional Logic (show/hide/require) ----------
  function parseRules() {
    const el = document.getElementById("sfb-rules-json");
    if (!el) return [];
    try { return JSON.parse(el.textContent || "[]") || []; } catch (e) { return []; }
  }

  function getFieldValue(formEl, fieldId) {
    const nodes = formEl.querySelectorAll('[data-field-id="' + fieldId + '"]');
    if (!nodes.length) return "";
    const first = nodes[0];
    if (first.type === "radio") {
      for (const n of nodes) if (n.checked) return n.value || "";
      return "";
    }
    if (first.type === "checkbox") {
      const vals = [];
      for (const n of nodes) if (n.checked) vals.push(n.value || "true");
      return vals;
    }
    return first.value || "";
  }

  function compare(op, left, right) {
    const r = (right ?? "").toString();
    const ln = Array.isArray(left) ? NaN : Number(left);
    const rn = Number(r);
    const numeric = !Number.isNaN(ln) && !Number.isNaN(rn);

    if (op === "contains") return (left ?? "").toString().includes(r);
    if (op === "=") return Array.isArray(left) ? left.map(String).includes(r) : (left ?? "").toString() === r;
    if (op === "!=") return Array.isArray(left) ? !left.map(String).includes(r) : (left ?? "").toString() !== r;
    if (op === "in" || op === "not in") {
      const wanted = r.split(",").map(s => s.trim()).filter(Boolean);
      const ok = Array.isArray(left) ? left.map(String).some(v => wanted.includes(v)) : wanted.includes((left ?? "").toString());
      return op === "in" ? ok : !ok;
    }
    if (numeric) {
      if (op === ">") return ln > rn;
      if (op === ">=") return ln >= rn;
      if (op === "<") return ln < rn;
      if (op === "<=") return ln <= rn;
    }
    return false;
  }

  function applyRules(formEl) {
    const rules = parseRules();
    for (const r of rules) {
      const v = getFieldValue(formEl, r.trigger);
      const ok = compare(r.op, v, r.value);
      const targetWrap = formEl.querySelector('.sfb-field[data-field-id="' + r.target + '"]');
      if (!targetWrap) continue;

      if (r.action === "show") targetWrap.style.display = ok ? "" : "none";
      else if (r.action === "hide") targetWrap.style.display = ok ? "none" : "";
      else if (r.action === "require") targetWrap.querySelectorAll("input,select,textarea").forEach(i => i.required = ok);
      else if (r.action === "unrequire") targetWrap.querySelectorAll("input,select,textarea").forEach(i => i.required = !ok);

      if (targetWrap.style.display === "none") {
        targetWrap.querySelectorAll("input,select,textarea").forEach((i) => {
          if (i.type === "checkbox" || i.type === "radio") i.checked = false;
          else i.value = "";
        });
      }
    }
  }


  function el(tag, cls, attrs) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (attrs) Object.entries(attrs).forEach(([k,v]) => e.setAttribute(k, v));
    return e;
  }

  function enhance(selectEl) {
    if (selectEl.dataset.sfbEnhanced === "1") return;
    selectEl.dataset.sfbEnhanced = "1";

    const opts = Array.from(selectEl.options).map(o => ({value:o.value, label:o.textContent || ""}));

    // Hide native select (still used for submission)
    selectEl.style.display = "none";

    const wrap = el("div", "sfb-dd");
    const btn = el("button", "form-select sfb-dd-btn", {type:"button"});
    const panel = el("div", "sfb-dd-panel d-none");
    const header = el("div", "sfb-dd-header");
    const search = el("input", "form-control sfb-dd-search", {type:"text", placeholder:"Search...", autocomplete:"off"});
    const list = el("div", "sfb-dd-list");

    header.appendChild(search);
    panel.appendChild(header);
    panel.appendChild(list);
    wrap.appendChild(btn);
    wrap.appendChild(panel);
    selectEl.parentNode.insertBefore(wrap, selectEl.nextSibling);

    function syncBtn() {
      const cur = selectEl.value;
      const found = opts.find(x => x.value === cur);
      btn.textContent = found ? found.label : (opts[0]?.label || "-- Select --");
    }

    function render(q) {
      const query = (q || "").toLowerCase().trim();
      list.innerHTML = "";

      // placeholder always first
      const ph = opts.find(o => o.value === "") || {value:"", label:"-- Select --"};
      const phItem = el("div", "sfb-dd-item sfb-dd-placeholder");
      phItem.textContent = ph.label;
      phItem.onclick = (e) => { e.preventDefault(); selectEl.value=""; selectEl.dispatchEvent(new Event("change",{bubbles:true})); syncBtn(); close(); };
      list.appendChild(phItem);

      let shown = 0;
      for (const o of opts) {
        if (o.value === "") continue;
        if (query && !o.label.toLowerCase().includes(query)) continue;
        const item = el("div", "sfb-dd-item" + (o.value===selectEl.value ? " active": ""));
        item.textContent = o.label;
        item.onclick = (e) => { e.preventDefault(); selectEl.value=o.value; selectEl.dispatchEvent(new Event("change",{bubbles:true})); syncBtn(); close(); };
        list.appendChild(item);
        shown++;
      }
      if (shown === 0) {
        const empty = el("div","sfb-dd-empty");
        empty.textContent = "No results";
        list.appendChild(empty);
      }
    }

    function open() {
      panel.classList.remove("d-none");
      render(search.value);
      setTimeout(() => { search.focus(); const v=search.value; search.setSelectionRange(v.length,v.length); }, 0);
    }
    function close() { panel.classList.add("d-none"); }

    btn.addEventListener("click",(e)=>{
      e.preventDefault(); e.stopPropagation();
      panel.classList.contains("d-none") ? open() : close();
    });

    // Keep dropdown open while typing/clicking inside
    ["click","mousedown","mouseup","keydown","keyup","keypress"].forEach(evt=>{
      panel.addEventListener(evt, e=>e.stopPropagation());
      search.addEventListener(evt, e=>e.stopPropagation());
      wrap.addEventListener(evt, e=>e.stopPropagation());
    });

    search.addEventListener("input", ()=>{
      const v = search.value;
      render(v);
      // preserve focus so user can type full name
      setTimeout(()=>{ search.focus(); search.setSelectionRange(v.length,v.length); },0);
    });

    document.addEventListener("click", close);

    syncBtn();
  }

  function init() {
    document.querySelectorAll("select.sfb-enhanced-select").forEach(enhance);
  }

  document.addEventListener("DOMContentLoaded", () => {
    const formEl = document.getElementById('smart-form');
    if (formEl) {
      applyRules(formEl);
      formEl.addEventListener('change', () => applyRules(formEl));
      formEl.addEventListener('input', () => applyRules(formEl));
    }

    init();
    setTimeout(init, 500);
  });
})();
