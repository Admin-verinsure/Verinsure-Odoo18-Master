/** @odoo-module **/

(function () {
  "use strict";

  // ---------- config ----------
  const LOG = "[auto-geocode]";
  const OPEN_TRIES = 12; // ~3s max wait for form to mount
  const OPEN_DELAY = 250; // ms between tries
  const CHANGE_DEBOUNCE = 600;

  // ---------- rpc helpers ----------
  async function rpc(route, params) {
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
  function callKw(model, method, args = [], kwargs = {}) {
    // canonical for Odoo 17/18
    return rpc("/web/dataset/call_kw", { model, method, args, kwargs });
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
    const hp = hashParams();
    if (hp.model === "res.partner" && hp.id && /^\d+$/.test(hp.id))
      return parseInt(hp.id, 10);
    const form = document.querySelector(".o_form_view");
    if (form) {
      const rid = form.getAttribute("data-res-id") || form.dataset.resId;
      if (rid && /^\d+$/.test(rid)) return parseInt(rid, 10);
    }
    const hid = document.querySelector('input[name="id"]');
    if (hid && /^\d+$/.test(hid.value)) return parseInt(hid.value, 10);
    return 0;
  }

  // ---------- trigger button function ----------
  const inFlight = new Map();
  async function triggerGeocode(id, why) {
    if (!id) return;
    if (inFlight.get(id)) return; // no parallel calls per record
    inFlight.set(id, true);
    try {
      // 1) Preferred: call the Python method directly (exactly like button)
      await callKw("res.partner", "action_locate_from_address", [[id]], {});
      console.debug(LOG, "RPC fired", { id, why });
    } catch (e) {
      console.warn(LOG, "RPC failed, fallback to click", { id, why, e });
      // 2) Fallback: click the real button in the DOM (same behavior)
      const btn = document.querySelector(
        'button[name="action_locate_from_address"]'
      );
      if (btn) {
        btn.click();
        console.debug(LOG, "Button clicked", { id, why });
      }
    } finally {
      inFlight.delete(id);
    }
  }

  function autoOnOpen() {
    let tries = 0;
    const tick = () => {
      const id = currentPartnerId();
      if (id) {
        triggerGeocode(id, "open");
        return;
      }
      if (++tries < OPEN_TRIES) {
        setTimeout(tick, OPEN_DELAY);
      } else {
        console.debug(LOG, "no partner id detected on open");
      }
    };
    tick();
  }

  function attachChangeListeners() {
    const sels = [
      'input[name="street"]',
      'input[name="street2"]',
      'input[name="city"]',
      'input[name="zip"]',
      'select[name="state_id"]',
      'select[name="country_id"]',
    ];
    const els = Array.from(document.querySelectorAll(sels.join(",")));
    let t = null;
    const schedule = () => {
      clearTimeout(t);
      t = setTimeout(() => {
        const id = currentPartnerId();
        if (id) triggerGeocode(id, "change");
      }, CHANGE_DEBOUNCE);
    };
    els.forEach((el) => {
      el.removeEventListener("input", schedule);
      el.removeEventListener("change", schedule);
      el.addEventListener("input", schedule);
      el.addEventListener("change", schedule);
    });
  }

  function init() {
    console.debug(LOG, "init");
    autoOnOpen();
    attachChangeListeners();

    window.addEventListener("hashchange", () => {
      setTimeout(() => {
        autoOnOpen();
        attachChangeListeners();
      }, 50);
    });

    const mo = new MutationObserver(() => {
      const form = document.querySelector(".o_form_view");
      if (form) {
        autoOnOpen();
        attachChangeListeners();
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
