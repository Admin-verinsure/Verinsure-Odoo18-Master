# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskTicket(models.Model):
    """
    Extend helpdesk.ticket with two extra website-form fields:
      - program_type  : mirrors res.partner.club_type selection field
      - ticket_club_id: Many2one to the res.partner record representing the club
    """
    _inherit = "helpdesk.ticket"

    # -------------------------------------------------------
    # Field 1 – Program Type
    # We reuse the same selection list as res.partner.club_type
    # so the two modules stay in sync automatically.
    # -------------------------------------------------------
    program_type = fields.Selection(
        selection=lambda self: self._get_club_type_selection(),
        string="Program Type",
        tracking=True,
    )

    # -------------------------------------------------------
    # Field 2 – Club Name  (res.partner record)
    # Filtered to partners whose club_type == program_type
    # -------------------------------------------------------
    ticket_club_id = fields.Many2one(
        comodel_name="res.partner",
        string="Club Name",
        domain="[('club_type', '=', program_type), ('active', '=', True)]",
        tracking=True,
    )

    # -------------------------------------------------------
    # Helper – pull selection values from res.partner.club_type
    # -------------------------------------------------------
    def _get_club_type_selection(self):
        field = self.env["res.partner"]._fields.get("club_type")
        if field and hasattr(field, "selection"):
            sel = field.selection
            if callable(sel):
                return sel(self.env["res.partner"])
            return sel or []
        return []
