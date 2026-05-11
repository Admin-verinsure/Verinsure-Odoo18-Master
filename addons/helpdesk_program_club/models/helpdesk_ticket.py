# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HelpdeskTicket(models.Model):
    """
    Extend helpdesk.ticket with:
      - program_type   : Selection mirroring res.partner.club_type
      - ticket_club_id : Many2one to the matching res.partner club record

    The website form POSTs these as plain string fields.
    We override create() so that even if the third-party controller
    passes them as strings (club_type key + partner id), they are
    coerced and written correctly.
    """
    _inherit = "helpdesk.ticket"

    # ── Field 1: Program Type ────────────────────────────────────────────
    program_type = fields.Selection(
        selection=lambda self: self._get_club_type_selection(),
        string="Program Type",
        tracking=True,
        index=True,
    )

    # ── Field 2: Club Name ───────────────────────────────────────────────
    ticket_club_id = fields.Many2one(
        comodel_name="res.partner",
        string="Club Name",
        domain="[('club_type', '=', program_type), ('active', '=', True)]",
        tracking=True,
        ondelete="set null",
    )

    # ── Helper ───────────────────────────────────────────────────────────
    def _get_club_type_selection(self):
        """Reuse the same selection list as res.partner.club_type."""
        field = self.env["res.partner"]._fields.get("club_type")
        if not field:
            return []
        sel = field.selection
        if callable(sel):
            return sel(self.env["res.partner"])
        return sel or []

    # ── create() hook – coerce website form string values ────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # ticket_club_id may arrive as a string "42" from the HTML form
            raw_club = vals.get("ticket_club_id")
            if isinstance(raw_club, str):
                try:
                    vals["ticket_club_id"] = int(raw_club) if raw_club.strip() else False
                except (ValueError, AttributeError):
                    vals["ticket_club_id"] = False

            # program_type should already be a string key, but sanitise
            raw_type = vals.get("program_type")
            if raw_type == "":
                vals["program_type"] = False

        return super().create(vals_list)
