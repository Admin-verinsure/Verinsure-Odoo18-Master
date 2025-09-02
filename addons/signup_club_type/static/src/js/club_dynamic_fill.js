/** @odoo-module **/

import publicWidget from "web.public.widget";
import rpc from "web.rpc";

publicWidget.registry.ClubDynamicFill = publicWidget.Widget.extend({
  selector: ".oe_signup_form, form",
  events: {
    'change select[name="club_type"]': "_onProgramChange",
  },

  start() {
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
    const program = ev.currentTarget.value || "";
    this._loadClubs(program, false);
  },

  _loadClubs(program, keepSelection) {
    const $club = this._clubSelect();
    if (!$club.length) return;

    const prev = keepSelection ? $club.val() : null;

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
            $club.append($("<option>", { value: String(c.id), text: c.name }));
          });
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

export default publicWidget.registry.ClubDynamicFill;
