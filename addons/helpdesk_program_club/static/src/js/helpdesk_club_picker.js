/** @odoo-module **/
/**
 * helpdesk_club_picker.js  — fully standalone
 *
 * Injects Program Type + Club Name dropdowns into the Odoo 18
 * s_website_form-based helpdesk page via DOM manipulation.
 * No QWeb template inheritance needed.
 *
 * Endpoints (standalone, no signup_club_type dependency):
 *   POST /helpdesk/program_types     → [{id, name}, …]
 *   POST /helpdesk/clubs_by_program  → [{id, name}, …]  (filtered by program_type_id)
 */

// ─── RPC ─────────────────────────────────────────────────────────────────────
function rpc(route, params = {}) {
    return fetch(route, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ jsonrpc: "2.0", method: "call", id: 1, params }),
    })
    .then(r => r.json())
    .then(d => {
        if (d.error) throw new Error(d.error.data?.message || "RPC error");
        return d.result;
    });
}

// ─── DOM helpers ─────────────────────────────────────────────────────────────
function makeOption(value, text) {
    const o = document.createElement("option");
    o.value = value ?? "";
    o.textContent = text ?? "";
    return o;
}

function makeSelect(id, name) {
    const s = document.createElement("select");
    s.id = id;
    s.name = name;
    s.className = "form-select s_website_form_input";
    s.required = true;
    return s;
}

function makeFormRow(labelText, ...inputEls) {
    const wrap = document.createElement("div");
    wrap.className = "mb-3 s_website_form_field s_website_form_custom s_website_form_required";
    wrap.style.display = "flex";
    wrap.style.flexWrap = "wrap";
    wrap.style.alignItems = "center";

    const lbl = document.createElement("label");
    lbl.className = "col-form-label s_website_form_label";
    lbl.style.width = "200px";
    lbl.style.minWidth = "200px";
    lbl.innerHTML = `${labelText} <span class="s_website_form_mark">*</span>`;

    const col = document.createElement("div");
    col.className = "col-lg";
    inputEls.forEach(el => col.appendChild(el));

    wrap.appendChild(lbl);
    wrap.appendChild(col);
    return wrap;
}

// ─── State ───────────────────────────────────────────────────────────────────
let allClubs = [];

// ─── Club loading ─────────────────────────────────────────────────────────────
async function loadClubs(programTypeId, clubSel, searchInp) {
    allClubs = [];
    clubSel.replaceChildren(makeOption("", "-- Select Program Type first --"));
    if (searchInp) searchInp.value = "";

    if (!programTypeId) return;

    clubSel.replaceChildren(makeOption("", "Loading…"));

    try {
        const clubs = await rpc("/helpdesk/clubs_by_program", {
            program_type_id: parseInt(programTypeId),
        });
        allClubs = clubs || [];

        if (!allClubs.length) {
            clubSel.replaceChildren(makeOption("", "-- No clubs found for this program --"));
            return;
        }
        clubSel.replaceChildren(
            makeOption("", "-- Select Club --"),
            ...allClubs.map(c => makeOption(String(c.id), c.name))
        );
    } catch (e) {
        console.error("[helpdesk_club_picker] club fetch:", e);
        clubSel.replaceChildren(makeOption("", "-- Error loading clubs --"));
    }
}

function filterClubs(clubSel, query) {
    const q = query.toLowerCase().trim();
    const list = q ? allClubs.filter(c => c.name.toLowerCase().includes(q)) : allClubs;
    clubSel.replaceChildren(
        makeOption("", list.length ? "-- Select Club --" : "-- No results --"),
        ...list.map(c => makeOption(String(c.id), c.name))
    );
}

// ─── Program Type loading ─────────────────────────────────────────────────────
async function loadProgramTypes(typeSel) {
    typeSel.replaceChildren(makeOption("", "Loading…"));
    try {
        const types = await rpc("/helpdesk/program_types");
        if (!types || !types.length) {
            typeSel.replaceChildren(makeOption("", "-- No program types found --"));
            console.warn("[helpdesk_club_picker] No program types in DB. Add some via Helpdesk > Configuration > Program Types.");
            return;
        }
        typeSel.replaceChildren(
            makeOption("", "-- Select Program Type --"),
            ...types.map(t => makeOption(String(t.id), t.name))
        );
    } catch (e) {
        console.error("[helpdesk_club_picker] program type fetch:", e);
        typeSel.replaceChildren(makeOption("", "-- Error loading program types --"));
    }
}

// ─── Find the helpdesk form on page ──────────────────────────────────────────
function findHelpdeskForm() {
    // 1. Explicit data-model attribute (most reliable)
    let form = document.querySelector('form[data-model="helpdesk.ticket"]');
    if (form) return form;

    // 2. s_website_form section whose form action contains "helpdesk"
    for (const sec of document.querySelectorAll("section.s_website_form")) {
        const f = sec.querySelector("form");
        if (f && (f.action || "").toLowerCase().includes("helpdesk")) return f;
    }

    // 3. Any s_website_form on a /helpdesk/* page
    if (window.location.pathname.toLowerCase().includes("helpdesk")) {
        const f = document.querySelector("section.s_website_form form");
        if (f) return f;
    }

    return null;
}

// ─── Find where to insert (just before submit button row) ─────────────────────
function findInsertBefore(form) {
    const btn = form.querySelector("button[type='submit'], .s_website_form_submit");
    if (!btn) return null;
    // Walk up to the direct child of form
    let el = btn;
    while (el && el.parentElement !== form) el = el.parentElement;
    return el || btn;
}

// ─── Main ─────────────────────────────────────────────────────────────────────
async function injectFields() {
    if (document.getElementById("hd_program_type_id")) return; // already injected

    const form = findHelpdeskForm();
    if (!form) {
        console.warn("[helpdesk_club_picker] Helpdesk form not found on this page.");
        return;
    }

    const insertBefore = findInsertBefore(form);
    if (!insertBefore) {
        console.warn("[helpdesk_club_picker] Submit button not found — appending to form.");
    }

    // ── Program Type ──────────────────────────────────────────────────────
    const typeSel = makeSelect("hd_program_type_id", "hd_program_type_id");
    const typeRow = makeFormRow("Program Type", typeSel);

    // ── Club Name (search + select) ───────────────────────────────────────
    const searchInp = document.createElement("input");
    searchInp.type = "text";
    searchInp.className = "form-control mb-1";
    searchInp.placeholder = "Search club…";
    searchInp.autocomplete = "off";
    searchInp.addEventListener("input", () => filterClubs(clubSel, searchInp.value));

    const clubSel = makeSelect("hd_club_id", "hd_club_id");
    clubSel.replaceChildren(makeOption("", "-- Select Program Type first --"));
    const clubRow = makeFormRow("Club Name", searchInp, clubSel);

    // ── Inject ────────────────────────────────────────────────────────────
    if (insertBefore) {
        form.insertBefore(typeRow, insertBefore);
        form.insertBefore(clubRow, insertBefore);
    } else {
        form.appendChild(typeRow);
        form.appendChild(clubRow);
    }

    // ── Wire up events ────────────────────────────────────────────────────
    typeSel.addEventListener("change", ev =>
        loadClubs(ev.target.value, clubSel, searchInp)
    );

    // ── Load data ─────────────────────────────────────────────────────────
    await loadProgramTypes(typeSel);

    console.log("[helpdesk_club_picker] Fields injected successfully.");
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectFields);
} else {
    injectFields();
}
