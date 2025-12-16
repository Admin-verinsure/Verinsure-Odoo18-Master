/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";
import { onMounted, onPatched } from "@odoo/owl";

// 1. Helper function remains the same
function ensureWizardNav(rootEl) {
  const notebook = rootEl.querySelector(".o_notebook");
  if (!notebook) return;

  const headerLinks = notebook.querySelectorAll(
    ".o_notebook_headers .nav-link"
  );
  if (!headerLinks.length) return;

  // prevent duplicate
  if (rootEl.querySelector(".o_wizard_nav")) return;

  const nav = document.createElement("div");
  nav.className = "o_wizard_nav";

  const prevBtn = document.createElement("button");
  prevBtn.type = "button";
  prevBtn.className = "btn btn-secondary";
  prevBtn.textContent = "Previous";

  const nextBtn = document.createElement("button");
  nextBtn.type = "button";
  nextBtn.className = "btn btn-primary";
  nextBtn.textContent = "Next";

  nav.appendChild(prevBtn);
  nav.appendChild(nextBtn);

  const sheet = rootEl.querySelector(".o_form_sheet");
  // Fallback to rootEl if sheet not found (e.g. dialogs)
  (sheet || rootEl).appendChild(nav);

  const getLinks = () =>
    notebook.querySelectorAll(".o_notebook_headers .nav-link");

  const getActiveIndex = () => {
    const links = Array.from(getLinks());
    const active = notebook.querySelector(
      ".o_notebook_headers .nav-link.active"
    );
    const idx = links.indexOf(active);
    return idx < 0 ? 0 : idx;
  };

  const goTo = (idx) => {
    const links = Array.from(getLinks());
    if (idx < 0 || idx >= links.length) return;
    links[idx].click();
    updateButtons();
  };

  const updateButtons = () => {
    const idx = getActiveIndex();
    const links = getLinks();
    prevBtn.disabled = idx <= 0;
    nextBtn.disabled = idx >= links.length - 1;
  };

  prevBtn.addEventListener("click", () => goTo(getActiveIndex() - 1));
  nextBtn.addEventListener("click", () => goTo(getActiveIndex() + 1));

  updateButtons();
}

// 2. Patch the Class (FormRenderer), NOT the prototype
patch(FormRenderer, "775_youth_program_application.notebook_wizard", {
  setup() {
    // 3. REMOVED: this._super(...arguments);
    // OWL setup methods run in parallel, no super call needed.

    const run = () => {
      // Ensure this.el exists (it does in onMounted/onPatched)
      // Check specifically for your wizard class to avoid affecting all forms
      if (this.el && this.el.classList.contains("o_notebook_wizard")) {
        ensureWizardNav(this.el);
      }
    };

    onMounted(run);
    onPatched(run);
  },
});
