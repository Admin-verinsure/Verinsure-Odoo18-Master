/** @odoo-module **/

/**
 * helpdesk_club_fill.js
 *
 * Handles the two dynamic dropdowns on the helpdesk ticket form:
 *   select#helpdesk_program_type  — Program Type
 *   select#helpdesk_club_id       — Club (filtered by Program Type)
 *
 * IMPORTANT: Because the form arch is stored as a static DB blob (view id=6350,
 * customised via website editor), the <select> elements are injected into the
 * arch by the post_init_hook with EMPTY option lists.
 *
 * This script therefore does TWO things on page load:
 *   1. Fetches Program Type options from /helpdesk/program_types and fills
 *      the Program Type <select>.
 *   2. If a Program Type is already selected (form re-post), fetches and fills
 *      the Club <select> immediately.
 *
 * Then on every Program Type change it refills the Club dropdown via
 * /helpdesk/clubs_by_type — same pattern as rotary_signup/club_dynamic_fill.js.
 */

// ── JSON-RPC helper ──────────────────────────────────────────────────────────

async function rpc(route, params) {
  try {
    const res = await fetch(route, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({
        jsonrpc: '2.0',
        method: 'call',
        id: Math.floor(Math.random() * 1e9),
        params: params || {},
      }),
    });
    const data = await res.json();
    return (data && data.result) || [];
  } catch (err) {
    console.error('[helpdesk_club_fill] RPC error on', route, err);
    return [];
  }
}

// ── DOM helper ───────────────────────────────────────────────────────────────

function opt(value, text) {
  const o = document.createElement('option');
  o.value = String(value ?? '');
  o.textContent = text || '';
  return o;
}

// ── Fill Program Type dropdown ───────────────────────────────────────────────

async function fillProgramTypes(typeSel) {
  const types = await rpc('/helpdesk/program_types');

  if (!types.length) {
    typeSel.replaceChildren(opt('', '-- No program types found --'));
    return;
  }

  typeSel.replaceChildren(
    opt('', '-- Select Program Type --'),
    ...types.map((t) => opt(t.value, t.label))
  );
}

// ── Fill Club dropdown ───────────────────────────────────────────────────────

async function fillClubs(clubType, clubSel) {
  if (!clubType) {
    clubSel.replaceChildren(opt('', '-- Select Program Type first --'));
    return;
  }

  clubSel.replaceChildren(opt('', 'Loading…'));
  clubSel.disabled = true;

  const clubs = await rpc('/helpdesk/clubs_by_type', { club_type: clubType });

  clubSel.disabled = false;

  if (!clubs.length) {
    clubSel.replaceChildren(opt('', '-- No clubs found for this program --'));
    return;
  }

  clubSel.replaceChildren(
    opt('', '-- Select Club --'),
    ...clubs.map((c) => opt(c.id, c.name))
  );
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  const typeSel = document.querySelector('select[name="helpdesk_program_type"]');
  const clubSel = document.querySelector('select[name="helpdesk_club_id"]');

  if (!typeSel || !clubSel) return;   // not on this page

  // Step 1: populate Program Type options from DB
  await fillProgramTypes(typeSel);

  // Step 2: if a value was pre-selected (form re-post after error), restore it
  //         and immediately load the corresponding clubs
  const preselected = typeSel.dataset.selected || '';
  if (preselected) {
    typeSel.value = preselected;
  }

  if (typeSel.value) {
    await fillClubs(typeSel.value, clubSel);
  } else {
    clubSel.replaceChildren(opt('', '-- Select Program Type first --'));
  }

  // Step 3: react to user changes
  typeSel.addEventListener('change', (ev) => {
    fillClubs(ev.target.value, clubSel);
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
