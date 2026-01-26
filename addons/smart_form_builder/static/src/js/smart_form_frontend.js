(function () {
  "use strict";

  function parseRules() {
    const el = document.getElementById("sfb-rules-json");
    if (!el) return [];
    try {
      const txt = (el.textContent || "[]").trim();
      return JSON.parse(txt || "[]") || [];
    } catch (e) {
      return [];
    }
  }

  function inputNodes(fid) {
    return document.querySelectorAll(
      'input[data-field-id="' + fid + '"],select[data-field-id="' + fid + '"],textarea[data-field-id="' + fid + '"]'
    );
  }

  function wrap(fid) {
    return document.querySelector('.sfb-field[data-field-id="' + fid + '"]');
  }

  function valueOf(fid) {
    const nodes = inputNodes(fid);
    if (!nodes.length) return "";
    const first = nodes[0];

    if (first.tagName === "SELECT") {
      const opt = first.options[first.selectedIndex];
      return { value: first.value || "", label: opt ? (opt.text || "") : "" };
    }

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

  function toNum(x) {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }

  function compare(op, left, right) {
    const r = (right ?? "").toString().trim();

    if ([">", ">=", "<", "<="].includes(op)) {
      const ln = Array.isArray(left) ? null : toNum(left);
      const rn = toNum(r);
      if (ln === null || rn === null) return false;
      if (op === ">") return ln > rn;
      if (op === ">=") return ln >= rn;
      if (op === "<") return ln < rn;
      if (op === "<=") return ln <= rn;
    }

    const want = r.toLowerCase();
    const vals = Array.isArray(left) ? left.map(String) : [String(left ?? "")];
    const valsLower = vals.map(v => v.toLowerCase());

    if (op === "contains") return valsLower.some(v => v.includes(want));
    if (op === "!=") return valsLower.every(v => v !== want);
    if (op === "in" || op === "not in") {
      const wanted = want.split(",").map(s => s.trim()).filter(Boolean);
      const ok = valsLower.some(v => wanted.includes(v));
      return op === "in" ? ok : !ok;
    }
    return valsLower.some(v => v === want);
  }

  function initLogic() {
    const rules = parseRules();
    if (!rules.length) return;

    const targets = new Set();
    for (const r of rules) if (r.action === "show") targets.add(String(r.target));
    for (const tid of targets) {
      const tw = wrap(tid);
      if (tw) tw.style.display = "none";
    }

    function apply() {
      for (const r of rules) {
        const trig = String(r.trigger);
        const targ = String(r.target);
        const tw = wrap(targ);
        if (!tw) continue;

        const ok = compare(r.op, valueOf(trig), r.value);

        if (r.action === "show") {
          tw.style.display = ok ? "" : "none";
          if (ok) {
            const trw = wrap(trig);
            if (trw && trw.nextElementSibling !== tw) {
              trw.parentNode.insertBefore(tw, trw.nextElementSibling);
            }
          } else {
            tw.querySelectorAll("input,select,textarea").forEach(i => {
              if (i.type === "checkbox" || i.type === "radio") i.checked = false;
              else i.value = "";
            });
          }
        } else if (r.action === "hide") {
          tw.style.display = ok ? "none" : "";
        } else if (r.action === "require") {
          tw.querySelectorAll("input,select,textarea").forEach(i => i.required = !!ok);
        } else if (r.action === "unrequire") {
          tw.querySelectorAll("input,select,textarea").forEach(i => i.required = !ok);
        }
      }
    }

    apply();

    const form = document.getElementById("smart-form");
    if (!form) return;
    let t = null;
    const handler = () => {
      if (t) clearTimeout(t);
      t = setTimeout(apply, 20);
    };
    form.addEventListener("input", handler, true);
    form.addEventListener("change", handler, true);
  }

  async function postJSON(url, payload) {
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
        credentials: "same-origin",
      });
      return res.ok ? await res.json() : null;
    } catch (e) {
      return null;
    }
  }

  function initBranchingOnSubmit() {
    const form = document.getElementById("smart-form");
    if (!form) return;

    form.addEventListener("submit", async (e) => {
      const tokenEl = document.querySelector('input[name="token"]');
      const token = tokenEl ? tokenEl.value : "";
      if (!token) return;

      e.preventDefault();

      const answers = {};
      document.querySelectorAll('input[data-field-id],select[data-field-id],textarea[data-field-id]').forEach(el => {
        const fid = el.getAttribute("data-field-id");
        if (!fid) return;

        if (el.tagName === "SELECT") {
          const opt = el.options[el.selectedIndex];
          answers[fid] = { value: el.value || "", label: opt ? (opt.text || "") : "" };
          return;
        }
        if (el.type === "radio") {
          if (el.checked) answers[fid] = el.value || "";
          return;
        }
        if (el.type === "checkbox") {
          if (!answers[fid]) answers[fid] = [];
          if (el.checked) answers[fid].push(el.value || "true");
          return;
        }
        answers[fid] = el.value || "";
      });

      const data = await postJSON("/smart_form/branching/" + encodeURIComponent(token), { answers });
      if (data && data.success && data.next_token) {
        window.location.href = "/smart_form/" + data.next_token;
        return;
      }
      form.submit();
    }, true);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initLogic();
    initBranchingOnSubmit();
  });
})();