/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { onMounted, onWillUpdateProps } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { FormController } from "@web/views/form/form_controller";

const NS = "[contact_location_cords:auto]";

function getIds(ctrl, props) {
  // Try props first (pager/nav keeps controller alive and only props change)
  const resModel =
    (props && props.resModel) ||
    (ctrl && ctrl.props && ctrl.props.resModel) ||
    (ctrl && ctrl.model && ctrl.model.root && ctrl.model.root.resModel) ||
    null;
  const resId =
    (props && props.resId) ||
    (ctrl && ctrl.props && ctrl.props.resId) ||
    (ctrl && ctrl.model && ctrl.model.root && ctrl.model.root.resId) ||
    (ctrl &&
      ctrl.props &&
      ctrl.props.context &&
      ctrl.props.context.active_id) ||
    null;
  return { resModel, resId };
}

patch(FormController.prototype, "contact_location_cords.AutoGeocodeOnForm", {
  setup() {
    this._super(...arguments);
    this.orm = useService("orm");
    this._autoGeoLastId = null;

    const run = async (id) => {
      if (!id || id === this._autoGeoLastId) return;
      this._autoGeoLastId = id;
      try {
        // Call your Python button exactly as if it was clicked
        await this.orm.call(
          "res.partner",
          "action_locate_from_address",
          [[id]],
          {}
        );
        // Refresh form so the fields reflect new values
        if (this.reload) {
          await this.reload();
        }
      } catch (e) {
        // Non-blocking; just log to console for debugging
        // eslint-disable-next-line no-console
        console.warn(NS, "auto geocode failed", { id, error: e });
      }
    };

    onMounted(() => {
      const { resModel, resId } = getIds(this, this.props);
      if (resModel === "res.partner" && resId) {
        run(resId);
      }
    });

    // Trigger again when navigating to another record with the pager
    onWillUpdateProps((nextProps) => {
      const { resModel, resId } = getIds(this, nextProps);
      if (resModel === "res.partner" && resId) {
        run(resId);
      }
    });
  },
});
