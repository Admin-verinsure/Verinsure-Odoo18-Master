odoo.define("rotary_signup.club_dynamic_fill", function (require) {
  "use strict";
  var ajax = require("web.ajax");

  $(document).ready(function () {
    const programSelect = $('select[name="program_type"]');
    const clubSelect = $('select[name="rotary_club_id"]');

    programSelect.on("change", function () {
      const clubType = $(this).val();
      clubSelect
        .empty()
        .append('<option value="">-- Select a Club --</option>');
      if (!clubType) return;

      ajax
        .jsonRpc("/clubs/by_program", "call", { club_type: clubType })
        .then(function (data) {
          $.each(data, function (i, club) {
            clubSelect.append(
              `<option value="${club.id}">${club.name}</option>`
            );
          });
        });
    });
  });
});
