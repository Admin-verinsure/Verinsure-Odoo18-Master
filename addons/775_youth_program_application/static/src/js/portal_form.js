/** Portal branching logic:
 * - Show/hide HomeStay block
 * - Show/hide criminal explain
 * - Sponsor other role field
 */
(function () {
  function byId(id) { return document.getElementById(id); }

  function toggleHomestay() {
    const cb = byId("is_homestay_volunteer");
    const block = byId("homestay_block");
    if (!cb || !block) return;
    block.style.display = cb.checked ? "block" : "none";
  }

  function toggleCriminalExplain() {
    const q1 = byId("criminal_q1");
    const q2 = byId("criminal_q2");
    const block = byId("criminal_explain_block");
    if (!block) return;
    const show = (q1 && q1.checked) || (q2 && q2.checked);
    block.style.display = show ? "block" : "none";
  }

  function toggleSponsorOther() {
    const sel = document.querySelector("select[name='sponsor_role']");
    const block = byId("sponsor_role_other_block");
    if (!sel || !block) return;
    block.style.display = (sel.value === "other") ? "block" : "none";
  }

  document.addEventListener("change", function (e) {
    if (e.target && e.target.id === "is_homestay_volunteer") toggleHomestay();
    if (e.target && (e.target.id === "criminal_q1" || e.target.id === "criminal_q2")) toggleCriminalExplain();
    if (e.target && e.target.name === "sponsor_role") toggleSponsorOther();
  });

  document.addEventListener("DOMContentLoaded", function () {
    toggleHomestay();
    toggleCriminalExplain();
    toggleSponsorOther();
  });
})();
