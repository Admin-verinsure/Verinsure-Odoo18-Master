/** @odoo-module **/
function optionEl(v, t) {
  const o = document.createElement("option");
  o.value = v || "";
  o.textContent = t || "";
  return o;
}
async function fetchClubs(clubType) {
  const res = await fetch("/clubs/by_program", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "call",
      params: { club_type: clubType },
    }),
  });
  const data = await res.json();
  return (data && data.result) || [];
}
async function fill(clubType, clubSel) {
  if (!clubType) {
    clubSel.replaceChildren(optionEl("", "-- Select Program Type first --"));
    return;
  }
  clubSel.replaceChildren(optionEl("", "Loading…"));
  try {
    const clubs = await fetchClubs(clubType);
    if (!clubs.length) {
      clubSel.replaceChildren(
        optionEl("", "-- No clubs found for this program --")
      );
      return;
    }
    clubSel.replaceChildren(
      ...clubs.map((c) => optionEl(String(c.id), c.name))
    );
  } catch (e) {
    console.error(e);
    clubSel.replaceChildren(optionEl("", "-- Error loading clubs --"));
  }
}
function init() {
  const typeSel = document.getElementById("club_type");
  const clubSel = document.getElementById("rotary_club_id");
  if (!typeSel || !clubSel) return;
  typeSel.value
    ? fill(typeSel.value, clubSel)
    : clubSel.replaceChildren(optionEl("", "-- Select Program Type first --"));
  typeSel.addEventListener("change", (ev) => fill(ev.target.value, clubSel));
}
document.readyState === "loading"
  ? document.addEventListener("DOMContentLoaded", init)
  : init();
