/** @odoo-module **/
/**
 * helpdesk_recaptcha.js
 * ─────────────────────
 * Odoo 18 frontend module.
 *
 * Responsibility
 * ──────────────
 * Odoo's own `website_recaptcha` JS already handles:
 *   • Loading api.js with the correct site key
 *   • Calling grecaptcha.execute() before the form is submitted
 *   • Populating the hidden `g-recaptcha-response` field
 *
 * This module's only job is to watch the server's AJAX response for
 * `{captcha_error: true}` and display a human-readable inline error
 * message instead of silently failing or reloading the page.
 *
 * Odoo 18 JS notes
 * ─────────────────
 * • `@odoo-module` at the top is the Odoo 18 ES-module marker.
 * • Import paths use the `@web/` alias (resolves via the asset bundler).
 * • `publicWidget` is the correct Odoo 18 API for extending website widgets.
 * • `.include({})` is Odoo's mixin pattern for patching existing classes
 *   without creating a new inheritance chain (equivalent to Python's
 *   _inherit on a model).
 * • `this._super(...arguments)` is Odoo 18's way of calling the patched
 *   original method.
 */

import publicWidget from '@web/legacy/js/public/public_widget';

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * Show the captcha error div inside the given form element.
 * Does nothing if the form or error div is not present.
 *
 * @param {HTMLElement|null} formEl
 * @param {string}           message
 */
function showCaptchaError(formEl, message) {
    if (!formEl) { return; }
    const errorDiv  = formEl.querySelector('#helpdesk_captcha_error');
    const errorText = formEl.querySelector('#helpdesk_captcha_error_text');
    if (!errorDiv) { return; }
    if (errorText) {
        errorText.textContent = message || 'CAPTCHA verification failed. Please try again.';
    }
    errorDiv.classList.remove('d-none');
    // Scroll the error into view smoothly so users on long forms see it.
    errorDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/**
 * Hide the captcha error div inside the given form element.
 *
 * @param {HTMLElement|null} formEl
 */
function hideCaptchaError(formEl) {
    if (!formEl) { return; }
    const errorDiv = formEl.querySelector('#helpdesk_captcha_error');
    if (errorDiv) { errorDiv.classList.add('d-none'); }
}


// ── Widget patch ──────────────────────────────────────────────────────────────

/**
 * Patch Odoo's WebsiteFormWidget to intercept the server response.
 *
 * WebsiteFormWidget (defined in website/static/src/js/content/website_form.js)
 * already handles the AJAX POST and success redirect.  We extend only the
 * method that processes the response so we can catch captcha_error payloads.
 *
 * The guard `?.include` means: only patch if the widget is registered
 * (i.e. website_form module is installed).  This prevents a crash if
 * the dependency is somehow absent.
 */
publicWidget.registry.WebsiteFormWidget?.include({

    // ── Reset error on every new submission attempt ───────────────────────
    /**
     * Called by Odoo's website_form before the AJAX request is sent.
     * We hide any previous error so the user gets fresh feedback.
     */
    _prepareSubmit() {
        const formEl = this.el?.querySelector
            ? this.el
            : document.getElementById('helpdesk_recaptcha_form');
        hideCaptchaError(formEl);
        return this._super(...arguments);
    },

    // ── Watch for captcha_error in the server response ────────────────────
    /**
     * Called after Odoo receives the JSON response from /website/form/.
     *
     * If the response contains `captcha_error: true` (set by our Python
     * controller when Google rejects the token), we:
     *   1. Show the inline error message.
     *   2. Return early – we do NOT call _super so Odoo's success path
     *      (redirect, thank-you message) does not run.
     *
     * For every other response we call _super so normal Odoo behaviour
     * is completely preserved.
     *
     * @param {Object} result  Parsed JSON from the server
     */
    _onFormSubmitDone(result) {
        if (result && result.captcha_error) {
            // Locate our specific helpdesk form (other forms won't have
            // #helpdesk_captcha_error so showCaptchaError is a no-op for them).
            const formEl = document.getElementById('helpdesk_recaptcha_form')
                        || this.el
                        || null;
            showCaptchaError(
                formEl,
                result.error || 'CAPTCHA verification failed. Please try again.',
            );
            // Do NOT call _super – we handled it.
            return;
        }

        // Not a captcha error → let Odoo's standard handler run.
        return this._super(...arguments);
    },
});
