/** Dynamic dropdown loader for public forms (zehntech_form_builder extension) */
odoo.define('dynamic_form_builder.dynamic_dropdown_frontend', [], function (require) {
    "use strict";

    async function loadOptionsForSelect(selectEl) {
        const fieldId = selectEl.dataset.fieldId;
        const token = selectEl.dataset.formToken;
        if (!fieldId) { return; }

        const url = token
            ? `/form_builder/dynamic_options/${fieldId}?token=${encodeURIComponent(token)}`
            : `/form_builder/dynamic_options/${fieldId}`;

        try {
            const res = await fetch(url, { method: 'GET', credentials: 'same-origin' });
            const data = await res.json();
            if (!data || !data.success) { return; }

            // Keep first placeholder option if any
            const firstOpt = selectEl.querySelector('option[value=""]') || selectEl.options[0] || null;
            const placeholder = firstOpt ? { value: firstOpt.value, label: firstOpt.textContent } : null;

            // Clear existing
            selectEl.innerHTML = '';

            // Restore placeholder
            if (placeholder) {
                const opt = document.createElement('option');
                opt.value = placeholder.value;
                opt.textContent = placeholder.label;
                selectEl.appendChild(opt);
            }

            (data.options || []).forEach((o) => {
                const option = document.createElement('option');
                option.value = o.value;
                option.textContent = o.label;
                selectEl.appendChild(option);
            });
        } catch (e) {
            // fail silently on public pages
            // console.error('dynamic options load failed', e);
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('select[data-dynamic-options="1"]').forEach((el) => {
            loadOptionsForSelect(el);
        });
    });
});
