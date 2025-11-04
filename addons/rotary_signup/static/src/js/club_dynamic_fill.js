/** @odoo-module **/

function optionEl(value, text) {
  const o = document.createElement("option");
  o.value = value || "";
  o.textContent = text || "";
  return o;
}

async function fetchClubs(programTypeId) {
  if (!programTypeId) return [];
  try {
    const res = await fetch("/club_lookup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "call",
        params: { program_type_id: parseInt(programTypeId) },
      }),
    });
    const data = await res.json();
    return (data && data.result) || [];
  } catch (err) {
    console.error("Error fetching clubs:", err);
    return [];
  }
}

async function fill(programTypeId, clubSelect) {
  if (!clubSelect) return;
  if (!programTypeId) {
    clubSelect.replaceChildren(optionEl("", "-- Select Program Type first --"));
    return;
  }

  clubSelect.replaceChildren(optionEl("", "Loading…"));
  const clubs = await fetchClubs(programTypeId);
  if (!clubs.length) {
    clubSelect.replaceChildren(
      optionEl("", "-- No clubs found for this program --")
    );
    return;
  }
  clubSelect.replaceChildren(
    ...clubs.map((c) => optionEl(String(c.id), c.name))
  );
}

function init() {
  const typeSel = document.querySelector('select[name="program_type_id"]');
  const clubSel = document.querySelector('select[name="rotary_club_id"]');

  if (!typeSel || !clubSel) return;

  // initial fill if value already selected
  if (typeSel.value) {
    fill(typeSel.value, clubSel);
  } else {
    clubSel.replaceChildren(optionEl("", "-- Select Program Type first --"));
  }

  // update on change
  typeSel.addEventListener("change", (ev) => fill(ev.target.value, clubSel));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
