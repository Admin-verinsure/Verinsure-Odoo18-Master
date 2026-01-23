(function () {
  "use strict";

  // Conditional Logic
  function parseRules(){const el=document.getElementById("sfb-rules-json");if(!el)return[];try{return JSON.parse(el.textContent||"[]")||[]}catch(e){return[]}}
  function getFieldValue(formEl,fieldId){const nodes=formEl.querySelectorAll('[data-field-id="'+fieldId+'"]');if(!nodes.length)return"";const first=nodes[0];if(first.type==="radio"){for(const n of nodes)if(n.checked)return n.value||"";return""}if(first.type==="checkbox"){const vals=[];for(const n of nodes)if(n.checked)vals.push(n.value||"true");return vals}return first.value||""}
  function compare(op,left,right){const r=(right??"").toString();const ln=Array.isArray(left)?NaN:Number(left);const rn=Number(r);const numeric=!Number.isNaN(ln)&&!Number.isNaN(rn);if(op==="contains")return (left??"").toString().includes(r);if(op==="=")return Array.isArray(left)?left.map(String).includes(r):(left??"").toString()===r;if(op==="!=")return Array.isArray(left)?!left.map(String).includes(r):(left??"").toString()!==r;if(op==="in"||op==="not in"){const wanted=r.split(",").map(s=>s.trim()).filter(Boolean);const ok=Array.isArray(left)?left.map(String).some(v=>wanted.includes(v)):wanted.includes((left??"").toString());return op==="in"?ok:!ok}if(numeric){if(op===">")return ln>rn;if(op===">=")return ln>=rn;if(op==="<")return ln<rn;if(op==="<=")return ln<=rn}return false}
  function applyRules(formEl){const rules=parseRules();for(const rule of rules){const v=getFieldValue(formEl,rule.trigger);const ok=compare(rule.op,v,rule.value);const target=formEl.querySelector('.sfb-field[data-field-id="'+rule.target+'"]');if(!target)continue;if(rule.action==="show")target.style.display=ok?"":"none";else if(rule.action==="hide")target.style.display=ok?"none":"";else if(rule.action==="require")target.querySelectorAll("input,select,textarea").forEach(i=>i.required=ok);else if(rule.action==="unrequire")target.querySelectorAll("input,select,textarea").forEach(i=>i.required=!ok);if(target.style.display==="none"){target.querySelectorAll("input,select,textarea").forEach(i=>{if(i.type==="checkbox"||i.type==="radio")i.checked=false;else i.value=""})}}}


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
    const formEl=document.getElementById('smart-form');
    if(formEl){applyRules(formEl);formEl.addEventListener('change',()=>applyRules(formEl));formEl.addEventListener('input',()=>applyRules(formEl));}

    init();
    // In case the page is partially re-rendered by website editor, try again shortly
    setTimeout(init, 500);
  });
})();