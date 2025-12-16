/** @odoo-module **/

import { FormRenderer } from "@web/views/form/form_renderer";
import { patch } from "@web/core/utils/patch";
import { onMounted, onPatched } from "@odoo/owl";

/**
 * Helper function to create the wizard buttons.
 * This remains mostly the same, but kept clean for Odoo 18.
 */
function ensureWizardNav(rootEl) {
  const notebook = rootEl.querySelector(".o_notebook");
  if (!notebook) return;

  const headerLinks = notebook.querySelectorAll(
    ".o_notebook_headers .nav-link"
  );
  if (!headerLinks.length) return;

  // Prevent duplicates
  if (rootEl.querySelector(".o_wizard_nav")) return;

  // Create container
  const nav = document.createElement("div");
  nav.className = "o_wizard_nav";

  // Create Buttons
  const prevBtn = document.createElement("button");
  prevBtn.classList.add("btn", "btn-secondary");
  prevBtn.textContent = "Previous";

  const nextBtn = document.createElement("button");
  nextBtn.classList.add("btn", "btn-primary");
  nextBtn.textContent = "Next";

  nav.appendChild(prevBtn);
  nav.appendChild(nextBtn);

  // Append to sheet or root
  const sheet = rootEl.querySelector(".o_form_sheet");
  (sheet || rootEl).appendChild(nav);

  // Navigation Logic
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
    if (idx >= 0 && idx < links.length) {
      links[idx].click();
      updateButtons();
    }
  };

  const updateButtons = () => {
    const idx = getActiveIndex();
    const links = getLinks();
    prevBtn.disabled = idx <= 0;
    nextBtn.disabled = idx >= links.length - 1;
  };

  prevBtn.onclick = () => goTo(getActiveIndex() - 1);
  nextBtn.onclick = () => goTo(getActiveIndex() + 1);

  updateButtons();
}

/**
 * PATCHING FOR ODOO 18
 * 1. Target: FormRenderer.prototype
 * 2. Arguments: Only 2 (Target, Methods) - DO NOT pass a string ID.
 * 3. Super: Use super.setup()
 */
patch(FormRenderer.prototype, {
  setup() {
    super.setup(); // Correct Odoo 18 super call

    const run = () => {
      // Check if this specific form is a wizard
      if (this.el && this.el.classList.contains("o_notebook_wizard")) {
        ensureWizardNav(this.el);
      }
    };

    onMounted(run);
    onPatched(run);
  },
});
