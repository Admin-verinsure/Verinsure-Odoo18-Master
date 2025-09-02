/** @odoo-module **/

import publicWidget from "@website/public_widget/public_widget";
import { jsonRpc } from "@web/core/network/rpc";

publicWidget.registry.ClubDynamicFill = publicWidget.Widget.extend({
  selector: ".oe_signup_form, form",
  events: {
    'change select[name="club_type"]': "_onProgramChange",
  },

  start() {
    const preset = this.$('select[name="club_type"]').val();
    if (preset) this._loadClubs(preset, true);
    return this._super(...arguments);
  },

  _onProgramChange(ev) {
    this._loadClubs(ev.currentTarget.value || "", false);
  },

  async _loadClubs(program, keepSelection) {
    const $club = this.$('select[name="rotary_club_id"]');
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

    if (!program) {
      $club.prop("disabled", false);
      return;
    }

    try {
      const clubs = await jsonRpc("/clubs/by_program", { club_type: program });
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
        for (const c of clubs) {
          $club.append($("<option>", { value: String(c.id), text: c.name }));
        }
        if (prev && $club.find(option[(value = "${prev}")]).length)
          $club.val(prev);
      }
    } catch (e) {
      $club
        .empty()
        .append(
          $("<option>", { value: "", text: "-- Unable to load clubs --" })
        );
      // optional: console.error(e);
    } finally {
      $club.prop("disabled", false);
    }
  },
});

export default publicWidget.registry.ClubDynamicFill;
