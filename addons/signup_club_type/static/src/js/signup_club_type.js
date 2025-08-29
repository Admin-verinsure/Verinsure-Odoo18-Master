odoo.define("signup_club_type.fill_program_type", function (require) {
  "use strict";

  const publicWidget = require("web.public.widget");

  publicWidget.registry.SignupClubType = publicWidget.Widget.extend({
    selector: "form.o_website_login_form, form#signup_form",
    start: function () {
      const $select = this.$('select[name="club_type"]');
      if (!$select.length || $select.children("option").length > 1) {
        // not on signup form or already filled
        return this._super.apply(this, arguments);
      }
      if (!(window.odoo && odoo.jsonRpc)) {
        return this._super.apply(this, arguments);
      }
      return odoo
        .jsonRpc("/signup/club_type_selection", "call", {})
        .then((rows) => {
          if (Array.isArray(rows)) {
            rows.forEach((r) => {
              $select.append(
                $("<option>").attr("value", r.value).text(r.label)
              );
            });
          }
        })
        .always(() => this._super.apply(this, arguments));
    },
  });
});
