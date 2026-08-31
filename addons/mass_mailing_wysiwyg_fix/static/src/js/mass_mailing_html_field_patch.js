/** @odoo-module **/

import { loadBundle } from "@web/core/assets";
import { patch } from "@web/core/utils/patch";
import { MassMailingHtmlField } from "@mass_mailing/js/mass_mailing_html_field";
import { HtmlField } from "@web_editor/js/backend/html_field";

patch(MassMailingHtmlField.prototype, {
    async _lazyloadWysiwyg(...args) {
        // Preserve the standard Web Editor initialization.
        await HtmlField.prototype._lazyloadWysiwyg.call(this, ...args);

        // Mass Mailing extends the Web Editor Wysiwyg class, but its
        // specialized module is contained in the lazy WYSIWYG bundle.
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
                "Mass Mailing WYSIWYG Fix: @mass_mailing/js/mass_mailing_wysiwyg could not be loaded."
            );
        }

        this.Wysiwyg = wysiwygModule.MassMailingWysiwyg;
    },
});