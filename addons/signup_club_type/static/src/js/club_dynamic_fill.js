odoo.define("signup_club_type.club_dynamic_fill", function (require) {
  "use strict";

  const publicWidget = require("web.public.widget");
  const rpc = require("web.rpc");

  publicWidget.registry.ClubDynamicFill = publicWidget.Widget.extend({
    selector: ".oe_signup_form, form", // broad enough to catch your form
    events: {
      'change select[name="club_type"]': "_onProgramChange",
    },

    start() {
      // If a program type is already selected (reload/validation), load clubs once
      const presetProgram = this._programSelect().val();
      if (presetProgram) {
        this._loadClubs(presetProgram, true);
      }
      return this._super(...arguments);
    },

    _programSelect() {
      return this.$('select[name="club_type"]');
    },

    _clubSelect() {
      return this.$('select[name="rotary_club_id"]');
    },

    _onProgramChange(ev) {
      const val = ev.currentTarget.value || "";
      this._loadClubs(val, false);
    },

    _loadClubs(program, keepSelection) {
      const $club = this._clubSelect();
      if (!$club.length) return;

      const prev = keepSelection ? $club.val() : null;

      // reset UI quickly
      $club
        .prop("disabled", true)
        .empty()
        .append(
          $("<option>", {
            value: "",
            text: program ? "Loading…" : "-- Select Program Type first --",
          })
        );

      if (!program) return;

      rpc
        .query({
          route: "/clubs/by_program",
          params: { club_type: program },
        })
        .then((clubs) => {
          $club.empty();
          if (!clubs || !clubs.length) {
            $club.append(
              $("<option>", {
                value: "",
                text: "-- No clubs found for this program --",
              })
            );
          } else {
            $club.append(
              $("<option>", { value: "", text: "-- Select a Club Name --" })
            );
            clubs.forEach((c) => {
              $club.append(
                $("<option>", { value: String(c.id), text: c.name })
              );
            });
            // restore previous selection if still present
            if (prev && $club.find(option[(value = "${prev}")]).length) {
              $club.val(prev);
            }
          }
        })
        .catch(() => {
          $club
            .empty()
            .append(
              $("<option>", { value: "", text: "-- Unable to load clubs --" })
            );
        })
        .always(() => {
          $club.prop("disabled", false);
        });
    },
  });

  return publicWidget;
});
