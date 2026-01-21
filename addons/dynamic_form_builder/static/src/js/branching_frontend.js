/** Branching: when a trigger field changes, ask server for next form token and dynamically show a link/button */
odoo.define('zt_form_builder_dynamic.branching_frontend', function (require) {
    "use strict";

    const ajax = require('web.ajax');

    function collectAnswers(formEl) {
        const answers = {};
        // assumes each input includes data-field-id set by template or name=field_<id>
        formEl.querySelectorAll('[data-field-id]').forEach((el) => {
            const fid = el.dataset.fieldId;
            if (!fid) return;

            if (el.type === 'checkbox') {
                answers[fid] = el.checked ? (el.value || 'true') : '';
            } else if (el.type === 'radio') {
                if (el.checked) answers[fid] = el.value;
            } else {
                answers[fid] = el.value;
            }
        });
        return answers;
    }

    function ensureBranchCta(formEl) {
        let cta = formEl.querySelector('#branch_next_form_cta');
        if (!cta) {
            cta = document.createElement('div');
            cta.id = 'branch_next_form_cta';
            cta.className = 'alert alert-info mt-3 d-none';
            cta.innerHTML = '<div class="d-flex align-items-center justify-content-between">' +
                '<div><strong>Next step:</strong> a different form is required based on your selection.</div>' +
                '<a class="btn btn-primary" target="_blank" rel="noopener">Open next form</a>' +
                '</div>';
            formEl.appendChild(cta);
        }
        return cta;
    }

    function wireBranching(formEl) {
        const tokenInput = formEl.querySelector('input[name="token"]');
        const token = tokenInput ? tokenInput.value : null;
        if (!token) return;

        // Trigger check on any change
        formEl.addEventListener('change', () => {
            const answers = collectAnswers(formEl);
            ajax.jsonRpc(`/form_builder/branching/${token}`, 'call', { answers: answers })
                .then((res) => {
                    if (!res || !res.success) return;
                    const cta = ensureBranchCta(formEl);
                    if (res.next_token) {
                        const link = cta.querySelector('a');
                        link.href = `/form_builder/shared/${res.next_token}`;
                        cta.classList.remove('d-none');
                    } else {
                        cta.classList.add('d-none');
                    }
                });
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('form[action="/form_builder/submit"]').forEach(wireBranching);
    });
});
