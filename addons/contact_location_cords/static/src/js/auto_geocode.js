/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";

// Auto-trigger geocoding when opening a res.partner form
patch(FormController.prototype, "partner_geocode_auto.autogeocode_on_open", {
    setup() {
        this._super(...arguments);
        this.orm = useService("orm");
    },

    async onMounted() {
        await this._super(...arguments);
        try {
            // Only on Contact forms
            if (this.props.resModel !== "res.partner") {
                return;
            }
            const rec = this.model?.root;
            const d = rec?.data;
            if (!d || !d.id) {
                return;
            }

            // Do we have *some* address?
            const hasAddr = Boolean(
                d.country_id || d.state_id || d.city || d.street || d.street2 || d.zip
            );

            // Are coords missing? (0.0 is considered missing here)
            const missing =
                !d.partner_latitude || d.partner_latitude === 0 ||
                !d.partner_longitude || d.partner_longitude === 0;

            if (hasAddr && missing) {
                // Call your server-side button method
                await this.orm.call(
                    "res.partner",
                    "action_locate_from_address",
                    [[d.id]],
                    { context: this.props.context }
                );
                // Reload the form to reflect updated coordinates
                if (this.reload) {
                    await this.reload();
                }
            }
        } catch (e) {
            // Non-blocking: if anything fails we just don't auto-geocode
            console.warn("Auto geocode skipped:", e);
        }
    },
});
