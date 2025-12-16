/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormRenderer } from "@web/views/form/form_renderer";
import { onMounted, onPatched } from "@odoo/owl";

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

patch(FormRenderer.prototype, "775_youth_program_application.notebook_wizard", {
  setup() {
    this._super(...arguments);

    const run = () => {
      if (this.el && this.el.classList.contains("o_notebook_wizard")) {
        ensureWizardNav(this.el);
      }
    };

    onMounted(run);
    onPatched(run);
  },
});
