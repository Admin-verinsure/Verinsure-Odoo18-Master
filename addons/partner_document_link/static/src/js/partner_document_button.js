/** @odoo-module **/
/**
 * partner_document_button.js
 *
 * Optional OWL patch for the partner form view.
 * In Odoo 18 the stat button defined in XML is usually enough,
 * but this file shows how to patch a component if needed
 * (e.g. to add a tooltip or extra client-side logic).
 *
 * Odoo 18 uses OWL 2 + the new patch() API from @web/core/utils/patch.
 */

import { patch } from '@web/core/utils/patch';
import { FormController } from '@web/views/form/form_controller';

/**
 * Example: patch FormController to log when a partner's document
 * button is clicked (extend as needed for custom behaviour).
 *
 * Remove or extend this patch if no extra JS logic is required —
 * the XML button + Python action_open_documents() are sufficient
 * for basic navigation.
 */
patch(FormController.prototype, {
    /**
     * @override
     * Hook into the form controller setup if additional
     * partner-document integration is needed here.
     */
    setup() {
        super.setup(...arguments);
        // Add custom hooks here if needed
    },
});
