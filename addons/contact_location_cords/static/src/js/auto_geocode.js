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
    // canonical endpoint (v17/v18)
    return rpcCall("/web/dataset/call_kw", { model, method, args, kwargs });
  }

  // ---------- helpers ----------
  function hashParams() {
    const h = (location.hash || "").replace(/^#/, "");
    const sp = new URLSearchParams(h);
    const o = {};
    for (const [k, v] of sp.entries()) o[k] = v;
    return o;
  }

  function currentPartnerId() {
    // 1) hash params
    const hp = hashParams();
    if (hp.model === "res.partner" && hp.id && /^\d+$/.test(hp.id))
      return parseInt(hp.id, 10);
    // 2) form attribute (v17+)
    const form = document.querySelector(".o_form_view");
    if (form) {
      const rid = form.getAttribute("data-res-id") || form.dataset.resId;
      if (rid && /^\d+$/.test(rid)) return parseInt(rid, 10);
    }
    // 3) hidden input fallback
    const hiddenId = document.querySelector('input[name="id"]');
    if (hiddenId && /^\d+$/.test(hiddenId.value))
      return parseInt(hiddenId.value, 10);
    return 0;
  }

  async function readForDecision(id) {
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
    return { hasAddr };
  }

  async function readCoords(id) {
    const recs = await callKw("res.partner", "read", [
      [id],
      [
        "partner_latitude",
        "partner_longitude",
        "club_latitude",
        "club_longitude",
      ],
    ]);
    const r = Array.isArray(recs) && recs[0] ? recs[0] : {};
    const lat = r.partner_latitude ?? r.club_latitude ?? null;
    const lng = r.partner_longitude ?? r.club_longitude ?? null;
    return { lat, lng };
  }

  function setNumber(sel, n) {
    const el = document.querySelector(sel);
    if (!el || n == null) return;
    el.value = String(n);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }
  function pushCoordsToInputs(lat, lng) {
    setNumber('input[name="partner_latitude"]', lat);
    setNumber('input[name="partner_longitude"]', lng);
    setNumber('input[name="club_latitude"]', lat);
    setNumber('input[name="club_longitude"]', lng);
  }

  // ---------- main logic ----------
  const inFlightById = new Map();
  let debounceTimer = null;

  async function autoGeocode(reason) {
    const id = currentPartnerId();
    if (!id) return;

    if (inFlightById.get(id)) return;
    inFlightById.set(id, true);
    try {
      // Always act on open if address exists (=> “as if” you clicked the button)
      const { hasAddr } = await readForDecision(id);
      if (!hasAddr) return;

      await callKw("res.partner", "action_locate_from_address", [[id]], {});
      // read back & show without full reload
      const { lat, lng } = await readCoords(id);
      if (lat != null && lng != null) {
        pushCoordsToInputs(lat, lng);
      }
    } catch (e) {
      console.warn("Auto geocode skipped:", e);
    } finally {
      inFlightById.delete(id);
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
      debounceTimer = setTimeout(() => autoGeocode("change"), 600);
    };
    els.forEach((el) => {
      el.removeEventListener("input", schedule);
      el.removeEventListener("change", schedule);
      el.addEventListener("input", schedule);
      el.addEventListener("change", schedule);
    });
  }

  function init() {
    // run shortly after form mounts
    setTimeout(() => {
      autoGeocode("open");
      attachAddressListeners();
    }, 250);

    // on SPA navigation (clicking another contact)
    window.addEventListener("hashchange", () => {
      setTimeout(() => {
        autoGeocode("open");
        attachAddressListeners();
      }, 50);
    });

    // in case OWL re-renders the form container
    const mo = new MutationObserver(() => {
      const form = document.querySelector(".o_form_view");
      if (form) {
        autoGeocode("open");
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
