/** @odoo-module **/

/**
 * helpdesk_club_fill.js
 *
 * Mirrors the pattern in rotary_signup/club_dynamic_fill.js:
 *  1. On page load, if a Program Type is already selected, populate the Club dropdown.
 *  2. On change of Program Type, call /helpdesk/clubs_by_type and refill the Club dropdown.
 *
 * Targets:
 *   select[name="helpdesk_program_type"]  – Program Type selector (static <select>)
 *   select[name="helpdesk_club_id"]       – Club selector (dynamically filled)
 */

// ── helpers ─────────────────────────────────────────────────────────────────

function optionEl(value, text) {
  const o = document.createElement("option");
  o.value = value != null ? String(value) : "";
  o.textContent = text || "";
  return o;
}

/**
 * Fetch clubs for a given club_type key via JSON-RPC.
 * Returns an array like [{ id: 123, name: "…" }, …].
 */
async function fetchClubs(clubType) {
  if (!clubType) return [];
  try {
    const res = await fetch("/helpdesk/clubs_by_type", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        id: Math.floor(Math.random() * 1e9),
        params: { club_type: clubType },
      }),
    });
    const data = await res.json();
    return (data && data.result) || [];
  } catch (err) {
    console.error("[helpdesk_club_fill] fetchClubs error:", err);
    return [];
  }
}

/**
 * Refill the Club <select> based on the chosen Program Type key.
 */
async function fillClubs(clubType, clubSelect) {
  if (!clubSelect) return;

  if (!clubType) {
    clubSelect.replaceChildren(
      optionEl("", "-- Select Program Type first --")
    );
    return;
  }

  // Show a loading placeholder while we wait
  clubSelect.replaceChildren(optionEl("", "Loading…"));
  clubSelect.disabled = true;

  const clubs = await fetchClubs(clubType);

  clubSelect.disabled = false;

  if (!clubs.length) {
    clubSelect.replaceChildren(
      optionEl("", "-- No clubs found for this program --")
    );
    return;
  }

  clubSelect.replaceChildren(
    optionEl("", "-- Select Club --"),
    ...clubs.map((c) => optionEl(String(c.id), c.name))
  );
}

// ── initialisation ────────────────────────────────────────────────────────────

function init() {
  const typeSel = document.querySelector('select[name="helpdesk_program_type"]');
  const clubSel = document.querySelector('select[name="helpdesk_club_id"]');

  if (!typeSel || !clubSel) {
    // Not on a page that has these fields – do nothing.
    return;
  }

  // If the page already has a value pre-selected (e.g., after a form error),
  // populate clubs immediately.
  if (typeSel.value) {
    fillClubs(typeSel.value, clubSel);
  } else {
    clubSel.replaceChildren(
      optionEl("", "-- Select Program Type first --")
    );
  }

  // React to user changes
  typeSel.addEventListener("change", (ev) => {
    fillClubs(ev.target.value, clubSel);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
