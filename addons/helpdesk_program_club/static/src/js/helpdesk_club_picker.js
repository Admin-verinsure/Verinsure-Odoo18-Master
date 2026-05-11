/** @odoo-module **/
/**
 * helpdesk_club_picker.js
 *
 * Adds dynamic Program Type + Club Name behaviour to the Odoo 18
 * default Helpdesk website form (/helpdesk/new or embedded form).
 *
 * Behaviour:
 *  1. On page load: populate Program Type dropdown from DB via JSON-RPC.
 *  2. When user selects a Program Type: fetch matching clubs and fill
 *     the Club Name dropdown.
 *  3. Club Name dropdown has a live search box above it that filters
 *     results client-side (and re-fetches if list is large).
 */

// ─── helpers ────────────────────────────────────────────────────────────────

function rpc(route, params = {}) {
  return fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ jsonrpc: "2.0", method: "call", id: 1, params }),
  })
    .then((r) => r.json())
    .then((d) => {
      if (d.error) throw new Error(d.error.data?.message || "RPC error");
      return d.result;
    });
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === "class") node.className = v;
    else if (k.startsWith("on"))
      node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  });
  children.forEach((c) =>
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c)
  );
  return node;
}

function optionEl(value, text) {
  const o = document.createElement("option");
  o.value = value ?? "";
  o.textContent = text ?? "";
  return o;
}

// ─── state ──────────────────────────────────────────────────────────────────

let allClubs = [];   // full list for current program type (for client search)

// ─── Club dropdown helpers ───────────────────────────────────────────────────

function renderClubs(clubSel, clubs) {
  clubSel.replaceChildren(
    ...clubs.map((c) => optionEl(String(c.id), c.name))
  );
}

function filterClubs(clubSel, query) {
  const q = query.toLowerCase().trim();
  const filtered = q
    ? allClubs.filter((c) => c.name.toLowerCase().includes(q))
    : allClubs;

  if (!filtered.length) {
    clubSel.replaceChildren(optionEl("", "-- No results --"));
  } else {
    renderClubs(clubSel, filtered);
  }
}

async function loadClubs(programType, clubSel, searchInput) {
  if (!programType) {
    allClubs = [];
    clubSel.replaceChildren(optionEl("", "-- Select Program Type first --"));
    if (searchInput) searchInput.value = "";
    return;
  }

  clubSel.replaceChildren(optionEl("", "Loading…"));
  if (searchInput) searchInput.value = "";

  try {
    const clubs = await rpc("/helpdesk/clubs_by_program", {
      club_type: programType,
    });
    allClubs = clubs || [];

    if (!allClubs.length) {
      clubSel.replaceChildren(
        optionEl("", "-- No clubs found for this program --")
      );
      return;
    }

    // Blank first option so user must actively choose
    clubSel.replaceChildren(
      optionEl("", "-- Select Club --"),
      ...allClubs.map((c) => optionEl(String(c.id), c.name))
    );
  } catch (e) {
    console.error("Helpdesk club fetch error:", e);
    clubSel.replaceChildren(optionEl("", "-- Error loading clubs --"));
  }
}

// ─── Program Type dropdown ───────────────────────────────────────────────────

async function loadProgramTypes(typeSel) {
  try {
    const types = await rpc("/helpdesk/program_types");
    if (!types || !types.length) return;

    typeSel.replaceChildren(
      optionEl("", "-- Select Program Type --"),
      ...types.map((t) => optionEl(t.key, t.label))
    );
  } catch (e) {
    console.error("Helpdesk program type fetch error:", e);
  }
}

// ─── Search input injection ──────────────────────────────────────────────────

function injectSearchBox(clubWrap, clubSel) {
  const searchInput = el("input", {
    type: "text",
    class: "form-control form-control-sm mb-1",
    placeholder: "Search club…",
    autocomplete: "off",
    id: "club_search",
  });

  searchInput.addEventListener("input", () =>
    filterClubs(clubSel, searchInput.value)
  );

  // Insert search box just before the <select>
  clubWrap.insertBefore(searchInput, clubSel);
  return searchInput;
}

// ─── Bootstrap ──────────────────────────────────────────────────────────────

async function init() {
  // ── Locate the Helpdesk form fields ──────────────────────────────────────
  // Odoo 18 helpdesk website form uses name attributes on inputs/selects.
  // We look for our injected select names (set via XML template override).
  const typeSel  = document.getElementById("helpdesk_program_type");
  const clubSel  = document.getElementById("helpdesk_club_id");

  if (!typeSel || !clubSel) return;   // not on a helpdesk form page

  const clubWrap = clubSel.parentElement;

  // Inject search box above the Club select
  const searchInput = injectSearchBox(clubWrap, clubSel);

  // Load program types from DB
  await loadProgramTypes(typeSel);

  // If there's already a value (e.g. form re-render after validation error),
  // pre-load clubs for that program type
  if (typeSel.value) {
    await loadClubs(typeSel.value, clubSel, searchInput);
  }

  // React to Program Type changes
  typeSel.addEventListener("change", (ev) =>
    loadClubs(ev.target.value, clubSel, searchInput)
  );
}

// Run after DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
