# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    """
    Add a program type link to res.partner so clubs can be
    associated with a program type independently of signup_club_type.
    """
    _inherit = "res.partner"

    helpdesk_program_type_id = fields.Many2one(
        comodel_name="helpdesk.program.type",
        string="Program Type (Helpdesk)",
        index=True,
        ondelete="set null",
    )


class HelpdeskTicket(models.Model):
    """
    Extend helpdesk.ticket with:
      - hd_program_type_id : Many2one to helpdesk.program.type
      - hd_club_id         : Many2one to res.partner (filtered by program type)
    """
    _inherit = "helpdesk.ticket"

    hd_program_type_id = fields.Many2one(
        comodel_name="helpdesk.program.type",
        string="Program Type",
        tracking=True,
        index=True,
        ondelete="set null",
    )

    hd_club_id = fields.Many2one(
        comodel_name="res.partner",
        string="Club Name",
        domain="[('helpdesk_program_type_id', '=', hd_program_type_id), ('active', '=', True)]",
        tracking=True,
        ondelete="set null",
    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        Coerce string values that arrive from the HTML form POST.
        The s_website_form snippet sends all values as strings.
        """
        for vals in vals_list:
            for key in ("hd_program_type_id", "hd_club_id"):
                raw = vals.get(key)
                if isinstance(raw, str):
                    try:
                        vals[key] = int(raw) if raw.strip() else False
                    except (ValueError, AttributeError):
                        vals[key] = False
        return super().create(vals_list)
