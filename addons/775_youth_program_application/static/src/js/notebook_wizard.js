/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";

function _ensureWizardNav(el) {
  // Find the notebook headers and pages
  const notebook = el.querySelector(".o_notebook");
  if (!notebook) return;

  const headerLinks = notebook.querySelectorAll(
    ".o_notebook_headers .nav-link"
  );
  if (!headerLinks.length) return;

  // Prevent duplicate nav
  if (el.querySelector(".o_wizard_nav")) return;

  // Create nav container
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

  // Put buttons at end of sheet (nice UX)
  const sheet = el.querySelector(".o_form_sheet");
  (sheet || el).appendChild(nav);

  const getActiveIndex = () => {
    const active = notebook.querySelector(
      ".o_notebook_headers .nav-link.active"
    );
    if (!active) return 0;
    return Array.from(headerLinks).indexOf(active);
  };

  const goTo = (idx) => {
    const links = notebook.querySelectorAll(".o_notebook_headers .nav-link");
    if (idx < 0 || idx >= links.length) return;
    links[idx].click(); // Switch page (works even if headers are hidden)
    updateButtons();
  };

  const updateButtons = () => {
    const idx = getActiveIndex();
    prevBtn.disabled = idx <= 0;
    nextBtn.disabled = idx >= headerLinks.length - 1;
  };

  prevBtn.addEventListener("click", () => goTo(getActiveIndex() - 1));
  nextBtn.addEventListener("click", () => goTo(getActiveIndex() + 1));

  updateButtons();
}

patch(FormRenderer.prototype, "775_youth_program_application.notebook_wizard", {
  mounted() {
    this._super(...arguments);
    if (this.el?.classList?.contains("o_notebook_wizard")) {
      _ensureWizardNav(this.el);
    }
  },
  patched() {
    this._super(...arguments);
    if (this.el?.classList?.contains("o_notebook_wizard")) {
      _ensureWizardNav(this.el);
    }
  },
});
