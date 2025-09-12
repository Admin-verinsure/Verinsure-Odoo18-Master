/** @odoo-module **/
(function () {
  "use strict";

  // ------------------ config ------------------
  const LOG = "[auto-geocode]";
  const OPEN_MAX_TRIES = 12; // ~3s (12 * 250ms) to wait for form mount
  const OPEN_TRY_DELAY = 250; // ms between tries
  const CHANGE_DEBOUNCE = 600; // ms debounce on address edits

  // ------------------ RPC helpers ------------------
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
    const msg = (data && data.error && data.error.message) || "RPC error";
    throw new Error(msg);
  }
  function callKw(model, method, args = [], kwargs = {}) {
    // Canonical endpoint for Odoo 17/18
    return rpc("/web/dataset/call_kw", { model, method, args, kwargs });
  }

  // ------------------ helpers ------------------
  function hashParams() {
    const h = (location.hash || "").replace(/^#/, "");
    const sp = new URLSearchParams(h);
    const o = {};
    for (const [k, v] of sp.entries()) o[k] = v;
    return o;
  }

  function currentPartnerId() {
    // 1) hash (#id=...&model=res.partner)
    const hp = hashParams();
    if (hp.model === "res.partner" && hp.id && /^\d+$/.test(hp.id))
      return parseInt(hp.id, 10);

    // 2) form attribute (Odoo sets data-res-id on form root)
    const form = document.querySelector(".o_form_view");
    if (form) {
      const rid = form.getAttribute("data-res-id") || form.dataset.resId;
      if (rid && /^\d+$/.test(rid)) return parseInt(rid, 10);
    }

    // 3) hidden input fallback
    const hid = document.querySelector('input[name="id"]');
    if (hid && /^\d+$/.test(hid.value)) return parseInt(hid.value, 10);

    return 0;
  }

  // ------------------ main trigger ------------------
  const inFlightById = new Map();
  let debounceTimer = null;
  let openClickArmed = false; // set true when user clicks a record in kanban/list

  async function triggerGeocode(id, why) {
    if (!id) return;
    if (inFlightById.get(id)) return; // avoid parallel calls per record
    inFlightById.set(id, true);
    try {
      await callKw("res.partner", "action_locate_from_address", [[id]], {});
      // Do NOT hard reload; the form will refresh itself or on next render
      console.debug(LOG, "geocode fired", { id, why });
    } catch (e) {
      console.warn(LOG, "geocode RPC failed", { id, why, error: e });
      // As a last resort, click the visible button if present (non-breaking)
      const btn = document.querySelector(
        'button[name="action_locate_from_address"]'
      );
      if (btn) {
        btn.click();
        console.debug(LOG, "fallback: button clicked", { id, why });
      }
    } finally {
      inFlightById.delete(id);
    }
  }

  function waitFormThenTrigger(why) {
    let tries = 0;
    const tick = () => {
      const id = currentPartnerId();
      const formReady = !!document.querySelector(".o_form_view");
      if (id && formReady) {
        triggerGeocode(id, why);
        return;
      }
      if (++tries < OPEN_MAX_TRIES) {
        setTimeout(tick, OPEN_TRY_DELAY);
      } else {
        console.debug(LOG, "gave up waiting for form", { why });
      }
    };
    tick();
  }

  // Fire when user chooses a contact from Kanban/List/Search
  function armOnRecordClicks() {
    const container = document.body;
    container.addEventListener(
      "click",
      (ev) => {
        const el = ev.target.closest(
          // Kanban cards, list rows, many2one search rows, etc.
          ".o_kanban_record, .o_data_row, tr.o_data_row, .o_dropdown_menu .o_menu_item, .o_searchview_result"
        );
        if (el) {
          openClickArmed = true;
          // After navigation, the hash will change and we’ll wait for the form then fire
        }
      },
      { capture: true }
    );
  }

  // Run on SPA navigation
  function onHashChange() {
    // If user clicked a record, we certainly want to fire; otherwise still fire (always on open)
    waitFormThenTrigger(openClickArmed ? "open-click" : "open");
    openClickArmed = false;
  }

  // Address field listeners (debounced)
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
      debounceTimer = setTimeout(() => {
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

  // Observe DOM to re-bind listeners after Owl re-renders
  function observeFormRenders() {
    const mo = new MutationObserver(() => {
      const form = document.querySelector(".o_form_view");
      if (form) {
        attachAddressListeners();
      }
    });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  function init() {
    console.debug(LOG, "init");
    armOnRecordClicks();
    // initial open (e.g., menu → last opened partner)
    waitFormThenTrigger("initial");
    attachAddressListeners();
    observeFormRenders();
    window.addEventListener("hashchange", () => {
      onHashChange();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
