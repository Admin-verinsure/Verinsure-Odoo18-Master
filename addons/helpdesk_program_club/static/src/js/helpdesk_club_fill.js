/** @odoo-module **/

/**
 * helpdesk_club_fill.js
 *
 * Populates Program Type and Club dropdowns on the helpdesk ticket form.
 * Mirrors rotary_signup/club_dynamic_fill.js exactly.
 *
 * Targets (already injected into view arch via Odoo shell):
 *   select#helpdesk_program_type  — filled from /helpdesk/program_types
 *   select#helpdesk_club_id       — filled from /helpdesk/clubs_by_type
 */

async function helpdeskRpc(route, params) {
    try {
        const response = await fetch(route, {
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
        const data = await response.json();
        return (data && data.result) || [];
    } catch (err) {
        console.error('[helpdesk_club_fill] RPC error:', route, err);
        return [];
    }
}

function makeOpt(value, label) {
    const o = document.createElement('option');
    o.value = value != null ? String(value) : '';
    o.textContent = label || '';
    return o;
}

async function fillProgramTypes(typeSel) {
    const types = await helpdeskRpc('/helpdesk/program_types');
    if (!types.length) {
        typeSel.replaceChildren(makeOpt('', '-- No program types found --'));
        return;
    }
    typeSel.replaceChildren(
        makeOpt('', '-- Select Program Type --'),
        ...types.map(t => makeOpt(t.value, t.label))
    );
}

async function fillClubs(clubType, clubSel) {
    if (!clubType) {
        clubSel.replaceChildren(makeOpt('', '-- Select Program Type first --'));
        return;
    }
    clubSel.replaceChildren(makeOpt('', 'Loading…'));
    clubSel.disabled = true;

    const clubs = await helpdeskRpc('/helpdesk/clubs_by_type', { club_type: clubType });
    clubSel.disabled = false;

    if (!clubs.length) {
        clubSel.replaceChildren(makeOpt('', '-- No clubs found --'));
        return;
    }
    clubSel.replaceChildren(
        makeOpt('', '-- Select Club --'),
        ...clubs.map(c => makeOpt(c.id, c.name))
    );
}

async function init() {
    const typeSel = document.querySelector('select#helpdesk_program_type');
    const clubSel = document.querySelector('select#helpdesk_club_id');

    if (!typeSel || !clubSel) return;

    // Fill program types from DB (same source as signup module)
    await fillProgramTypes(typeSel);

    // If re-posting after validation error, restore previous value and clubs
    if (typeSel.value) {
        await fillClubs(typeSel.value, clubSel);
    } else {
        clubSel.replaceChildren(makeOpt('', '-- Select Program Type first --'));
    }

    // On change: reload clubs
    typeSel.addEventListener('change', function (ev) {
        fillClubs(ev.target.value, clubSel);
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
