/** @odoo-module **/

(function () {
  "use strict";

  // ---------- RPC helpers ----------
  async function rpcCall(route, params) {
    const payload = {
      jsonrpc: "2.0",
      method: "call",
      params,
      id: Math.floor(Math.random() * 1e9),
    };
    const res = await fetch(route, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data && Object.prototype.hasOwnProperty.call(data, "result"))
      return data.result;
    throw new Error((data && data.error && data.error.message) || "RPC error");
  }

  async function callKw(model, method, args = [], kwargs = {}) {
    // ✔ canonical endpoint for v17/18
    return rpcCall("/web/dataset/call_kw", { model, method, args, kwargs });
  }

  // ---------- ID & hash helpers ----------
  function hashParams() {
    const h = (location.hash || "").replace(/^#/, "");
    const sp = new URLSearchParams(h);
    const o = {};
    for (const [k, v] of sp.entries()) o[k] = v;
    return o;
  }

  function currentPartnerId() {
    // 1) hash (#id=..&model=res.partner)
    const hp = hashParams();
    if (hp.model === "res.partner" && hp.id && /^\d+$/.test(hp.id))
      return parseInt(hp.id, 10);

    // 2) DOM fallback: Odoo sets data-res-id on the form root in v17+
    const form = document.querySelector(".o_form_view");
    if (form) {
      const rid = form.getAttribute("data-res-id") || form.dataset.resId;
      if (rid && /^\d+$/.test(rid)) return parseInt(rid, 10);
    }

    // 3) last resort: look for hidden input widgets
    const hiddenId = document.querySelector('input[name="id"]');
    if (hiddenId && /^\d+$/.test(hiddenId.value))
      return parseInt(hiddenId.value, 10);

    return 0;
  }

  // ---------- address & coords via RPC ----------
  async function readMinimal(id) {
    const recs = await callKw("res.partner", "read", [
      [id],
      [
        "street",
        "street2",
        "city",
        "zip",
        "state_id",
        "country_id",
        "partner_latitude",
        "partner_longitude",
        "club_latitude",
        "club_longitude",
      ],
    ]);
    const r = Array.isArray(recs) && recs[0] ? recs[0] : {};
    const hasAddr = !!(
      r.street ||
      r.street2 ||
      r.city ||
      r.zip ||
      (r.state_id && r.state_id[0]) ||
      (r.country_id && r.country_id[0])
    );
    const plat = r.partner_latitude ?? null;
    const plng = r.partner_longitude ?? null;
    const clat = r.club_latitude ?? null;
    const clng = r.club_longitude ?? null;
    const lat = plat != null ? plat : clat;
    const lng = plng != null ? plng : clng;
    const coordsMissing = !(
      lat &&
      Math.abs(lat) > 1e-10 &&
      lng &&
      Math.abs(lng) > 1e-10
    );
    return { hasAddr, coordsMissing };
  }

  // ---------- auto trigger ----------
  const firedOnOpen = new Set();
  let debounceTimer = null;

  async function maybeAutoGeocode(reason) {
    try {
      const id = currentPartnerId();
      if (!id) return;

      if (reason === "open" && firedOnOpen.has(id)) return;

      // read from server (more reliable than DOM)
      const { hasAddr, coordsMissing } = await readMinimal(id);

      if (hasAddr && coordsMissing) {
        // Call your existing Python button
        await callKw("res.partner", "action_locate_from_address", [[id]], {});
        // no need to force reload; fields will show after the next render
      }

      if (reason === "open") firedOnOpen.add(id);
    } catch (e) {
      console.warn("Auto geocode skipped:", e);
    }
  }

  function attachAddressListeners() {
    const sels = [
      'input[name="street"]',
      'input[name="street2"]',
      'input[name="city"]',
      'input[name="zip"]',
      'select[name="state_id"]',
      'select[name="country_id"]',
    ];
    const els = Array.from(document.querySelectorAll(sels.join(",")));
    const schedule = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => maybeAutoGeocode("change"), 700);
    };
    els.forEach((el) => {
      el.removeEventListener("input", schedule);
      el.removeEventListener("change", schedule);
      el.addEventListener("input", schedule);
      el.addEventListener("change", schedule);
    });
  }

  function init() {
    // first run (after SPA has mounted)
    setTimeout(() => {
      maybeAutoGeocode("open");
      attachAddressListeners();
    }, 300);

    // on hash navigation (next/prev record, menu, etc.)
    window.addEventListener("hashchange", () => {
      setTimeout(() => {
        maybeAutoGeocode("open");
        attachAddressListeners();
      }, 50);
    });

    // watch for re-renders (form replaced by Owl)
    const mo = new MutationObserver(() => {
      const form = document.querySelector(".o_form_view");
      if (form) {
        maybeAutoGeocode("open");
        attachAddressListeners();
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
