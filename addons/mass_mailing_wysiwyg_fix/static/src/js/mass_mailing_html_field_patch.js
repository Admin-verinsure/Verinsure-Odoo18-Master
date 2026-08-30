/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { patch } from "@web/core/utils/patch";
import { MassMailingHtmlField } from "@mass_mailing/js/mass_mailing_html_field";
import { HtmlField } from "@web_editor/js/backend/html_field";

patch(MassMailingHtmlField.prototype, {
    async _lazyloadWysiwyg(...args) {
        // Call HtmlField directly instead of the original MassMailingHtmlField
        // implementation so we can avoid the failing module lookup path and
        // preserve the base editor lazy-loading behavior.
        await HtmlField.prototype._lazyloadWysiwyg.call(this, ...args);

        let wysiwygModule = await odoo.loader.modules.get(
            "@mass_mailing/js/mass_mailing_wysiwyg"
        );
        if (!wysiwygModule) {
            await loadBundle("web_editor.backend_assets_wysiwyg");
            wysiwygModule = await odoo.loader.modules.get(
                "@mass_mailing/js/mass_mailing_wysiwyg"
            );
        }
        if (!wysiwygModule?.MassMailingWysiwyg) {
            throw new Error(
                "Mass Mailing WYSIWYG Fix: failed to load @mass_mailing/js/mass_mailing_wysiwyg from web_editor.backend_assets_wysiwyg"
            );
        }

        this.Wysiwyg = wysiwygModule.MassMailingWysiwyg;
    },
});
