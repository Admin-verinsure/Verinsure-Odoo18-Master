/** @odoo-module **/

const CLUB_TYPE_SELECTOR = 'select[name="club_type"]';
const CLUB_NAME_SELECTOR = 'select[name="rotary_club_id"]';

async function jsonRpc(route, params) {
  const payload = {
    jsonrpc: "2.0",
    method: "call",
    params: params || {},
    id: Math.floor(Math.random() * 1e9),
  };
  const res = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (data && typeof data === "object" && "result" in data) return data.result;
  return [];
}

function setOptions(selectEl, options, placeholder) {
  selectEl.innerHTML = "";
  if (placeholder) {
    selectEl.add(new Option(placeholder, ""));
  }
  for (const opt of options) {
    selectEl.add(new Option(opt.text, opt.value));
  }
}

async function handleProgramChange(program, keepPrev) {
  const clubSelect = document.querySelector(CLUB_NAME_SELECTOR);
  if (!clubSelect) return;

  const prev = keepPrev ? clubSelect.value : null;
  clubSelect.disabled = true;

  if (!program) {
    setOptions(clubSelect, [], "-- Select Program Type first --");
    clubSelect.disabled = false;
    return;
  }

  setOptions(clubSelect, [], "Loading…");

  try {
    const clubs = await jsonRpc("/clubs/by_program", { club_type: program });
    if (!clubs || !clubs.length) {
      setOptions(clubSelect, [], "-- No clubs found for this program --");
    } else {
      const opts = clubs.map((c) => ({ text: c.name, value: String(c.id) }));
      setOptions(clubSelect, [], "-- Select a Club Name --");
      opts.forEach((o) => clubSelect.add(new Option(o.text, o.value)));
      if (
        prev &&
        Array.from(clubSelect.options).some((o) => o.value === prev)
      ) {
        clubSelect.value = prev;
      }
    }
  } catch (e) {
    setOptions(clubSelect, [], "-- Unable to load clubs --");
  } finally {
    clubSelect.disabled = false;
  }
}

function init() {
  const programSelect = document.querySelector(CLUB_TYPE_SELECTOR);
  const clubSelect = document.querySelector(CLUB_NAME_SELECTOR);
  if (!programSelect || !clubSelect) return;

  // bind change
  programSelect.addEventListener("change", (ev) => {
    handleProgramChange(ev.target.value || "", false);
  });

  // preload if a program is already selected
  if (programSelect.value) {
    handleProgramChange(programSelect.value, true);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
