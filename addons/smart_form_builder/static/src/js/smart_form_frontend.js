(function () {
  "use strict";

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
    init();
    setTimeout(init, 500);
  });
})();
