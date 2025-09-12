/** @odoo-module **/

(function () {
  "use strict";

  // ----- helpers -----
  function hashParams() {
    const h = (window.location.hash || "").replace(/^#/, "");
    const sp = new URLSearchParams(h);
    const o = {};
    for (const [k, v] of sp.entries()) o[k] = v;
    return o;
  }

  async function callKw(model, method, args = [], kwargs = {}) {
    const url = `/web/dataset/call_kw/${encodeURIComponent(
      model
    )}/${encodeURIComponent(method)}`;
    const payload = {
      jsonrpc: "2.0",
      method: "call",
      params: { model, method, args, kwargs },
      id: Math.floor(Math.random() * 1e9),
    };
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (data && typeof data === "object" && "result" in data)
      return data.result;
    throw new Error((data && data.error && data.error.message) || "RPC error");
  }

  function qs(sel) {
    return document.querySelector(sel);
  }
  function qsa(sel) {
    return Array.from(document.querySelectorAll(sel));
  }
  function val(el) {
    return el ? String(el.value || "").trim() : "";
  }

  function hasAddress() {
    return !!(
      val(qs('input[name="street"]')) ||
      val(qs('input[name="street2"]')) ||
      val(qs('input[name="city"]')) ||
      val(qs('input[name="zip"]')) ||
      val(qs('select[name="state_id"]')) ||
      val(qs('select[name="country_id"]'))
    );
  }

  function getNumber(sel) {
    const el = qs(sel);
    if (!el) return null;
    const s = val(el);
    if (!s) return null;
    const num = Number(s);
    return Number.isFinite(num) ? num : null;
  }

  function setNumber(sel, valNum) {
    const el = qs(sel);
    if (!el) return;
    if (valNum == null) return;
    el.value = String(valNum);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function coordsMissing() {
    // Prefer partner_*; fall back to club_*
    const lat =
      getNumber('input[name="partner_latitude"]') ??
      getNumber('input[name="club_latitude"]');
    const lng =
      getNumber('input[name="partner_longitude"]') ??
      getNumber('input[name="club_longitude"]');
    const latMissing = lat == null || lat === 0;
    const lngMissing = lng == null || lng === 0;
    return latMissing || lngMissing;
  }

  async function readCoords(id) {
    const r = await callKw(
      "res.partner",
      "read",
      [
        [id],
        [
          "partner_latitude",
          "partner_longitude",
          "club_latitude",
          "club_longitude",
        ],
      ],
      {}
    );
    const rec = Array.isArray(r) && r.length ? r[0] : {};
    return {
      lat: rec.partner_latitude ?? rec.club_latitude ?? null,
      lng: rec.partner_longitude ?? rec.club_longitude ?? null,
    };
  }

  function pushCoordsToInputs(lat, lng) {
    setNumber('input[name="partner_latitude"]', lat);
    setNumber('input[name="partner_longitude"]', lng);
    setNumber('input[name="club_latitude"]', lat);
    setNumber('input[name="club_longitude"]', lng);
  }

  // ----- main -----
  const triggeredOnOpen = new Set();
  let debounceTimer = null;

  async function tryAutoGeocode(reason) {
    try {
      const hp = hashParams();
      if (hp.model !== "res.partner") return;
      const id = parseInt(hp.id || "0", 10);
      if (!id) return;

      // On open, run once per record
      if (reason === "open" && triggeredOnOpen.has(id)) return;

      if (hasAddress() && coordsMissing()) {
        // Call your server-side method (same as pressing the button)
        await callKw("res.partner", "action_locate_from_address", [[id]], {});
        // Read back and inject into inputs so user sees the change immediately
        const { lat, lng } = await readCoords(id);
        if (lat != null && lng != null) {
          pushCoordsToInputs(lat, lng);
        }
      }

      if (reason === "open") triggeredOnOpen.add(id);
    } catch (e) {
      // non-blocking
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
    const els = qsa(sels.join(","));
    const schedule = () => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => tryAutoGeocode("change"), 800);
    };
    els.forEach((el) => {
      el.addEventListener("input", schedule);
      el.addEventListener("change", schedule);
    });
  }

  function init() {
    // Trigger on initial load / navigation
    tryAutoGeocode("open");
    attachAddressListeners();

    // Re-check on SPA navigation
    window.addEventListener("hashchange", () =>
      setTimeout(() => {
        tryAutoGeocode("open");
        attachAddressListeners();
      }, 0)
    );

    // Re-check when form DOM is (re)rendered
    const mo = new MutationObserver(() => {
      const form = document.querySelector(".o_form_view");
      if (form) {
        tryAutoGeocode("open");
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
