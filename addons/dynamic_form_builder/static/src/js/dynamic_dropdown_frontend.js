/** Dynamic dropdown loader for public forms (zehntech_form_builder extension) */
odoo.define('zt_form_builder_dynamic.dynamic_dropdown_frontend', function (require) {
    "use strict";

    const ajax = require('web.ajax');

    function loadOptionsForSelect(selectEl) {
        const fieldId = selectEl.dataset.fieldId;
        const token = selectEl.dataset.formToken;
        if (!fieldId || !token) { return; }

        ajax.jsonRpc(`/form_builder/dynamic_options/${fieldId}`, 'call', { token: token })
            .then((res) => {
                if (!res || !res.success) { return; }
                // keep first placeholder option if any
                const keep = [];
                for (const opt of selectEl.options) {
                    if (!opt.value) keep.push(opt);
                }
                selectEl.innerHTML = '';
                keep.forEach(o => selectEl.appendChild(o));
                res.options.forEach((o) => {
                    const option = document.createElement('option');
                    option.value = o.value;
                    option.textContent = o.label;
                    selectEl.appendChild(option);
                });
            });
    }

    document.addEventListener('DOMContentLoaded', () => {
        // Convention: dynamic select elements have data-dynamic-options="1"
        document.querySelectorAll('select[data-dynamic-options="1"]').forEach(loadOptionsForSelect);
    });
});
