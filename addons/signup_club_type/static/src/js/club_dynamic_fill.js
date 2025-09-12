/** @odoo-module **/

// ---------- helpers ----------
function hashParams() {
  const h = (window.location.hash || "").replace(/^#/, "");
  const sp = new URLSearchParams(h);
  const obj = {};
  for (const [k, v] of sp.entries()) obj[k] = v;
  return obj;
}

async function callKw(model, method, args = [], kwargs = {}) {
  const payload = {
    jsonrpc: "2.0",
    method: "call",
    params: { model, method, args, kwargs },
    id: Math.floor(Math.random() * 1e9),
  };
  const url = `/web/dataset/call_kw/${encodeURIComponent(
    model
  )}/${encodeURIComponent(method)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (data && typeof data === "object" && "result" in data) return data.result;
  throw new Error(
    data && data.error ? data.error.message || "RPC error" : "RPC error"
  );
}

function qs(sel) {
  return document.querySelector(sel);
}
function anyValue(els) {
  return els.some((el) => el && String(el.value || "").trim() !== "");
}
function getInputValue(sel) {
  const el = qs(sel);
  if (!el) return null;
  const v = String(el.value || "").trim();
  return v === "" ? null : Number(v);
}
function setInputValue(sel, val) {
  const el = qs(sel);
  if (!el) return;
  el.value = val == null ? "" : String(val);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
}

// ---------- main logic ----------
const triggeredIds = new Set();

async function tryAutoGeocode() {
  const hp = hashParams();
  if (hp.model !== "res.partner") return;
  const id = parseInt(hp.id || "0", 10);
  if (!id || triggeredIds.has(id)) return;

  // Detect address presence (loose)
  const hasAddr = anyValue([
    qs('input[name="street"]'),
    qs('input[name="street2"]'),
    qs('input[name="city"]'),
    qs('input[name="zip"]'),
    qs('select[name="state_id"]'),
    qs('select[name="country_id"]'),
  ]);

  // Read current coords from either built-ins or club_* if present
  const lat =
    getInputValue('input[name="partner_latitude"]') ??
    getInputValue('input[name="club_latitude"]');
  const lng =
    getInputValue('input[name="partner_longitude"]') ??
    getInputValue('input[name="club_longitude"]');

  // Missing if null or 0
  const missing = lat == null || lat === 0 || lng == null || lng === 0;

  if (hasAddr && missing) {
    try {
      // Call your python method (same as pressing the button)
      await callKw("res.partner", "action_locate_from_address", [[id]], {});
      // Read back values to update the visible inputs immediately
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
      const newLat = rec.partner_latitude ?? rec.club_latitude ?? null;
      const newLng = rec.partner_longitude ?? rec.club_longitude ?? null;

      // Write into whichever inputs exist
      if (qs('input[name="partner_latitude"]'))
        setInputValue('input[name="partner_latitude"]', newLat);
      if (qs('input[name="partner_longitude"]'))
        setInputValue('input[name="partner_longitude"]', newLng);
      if (qs('input[name="club_latitude"]'))
        setInputValue('input[name="club_latitude"]', newLat);
      if (qs('input[name="club_longitude"]'))
        setInputValue('input[name="club_longitude"]', newLng);
    } catch (e) {
      console.warn("Auto geocode failed:", e);
    }
  }

  // Prevent re-trigger on the same record
  triggeredIds.add(id);
}

// Run once on load, and again on hash or DOM changes (SPA navigation)
function init() {
  tryAutoGeocode();
  window.addEventListener("hashchange", () => setTimeout(tryAutoGeocode, 0));
  const obs = new MutationObserver(() => {
    // When the form view is inserted/re-rendered, try again (but 'triggeredIds' prevents loops)
    const form = document.querySelector(".o_form_view");
    if (form) setTimeout(tryAutoGeocode, 0);
  });
  obs.observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
