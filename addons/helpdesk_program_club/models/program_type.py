# -*- coding: utf-8 -*-
from odoo import fields, models


class HelpdeskProgramType(models.Model):
    """
    Standalone lookup table for Program Types.
    Managed from Helpdesk > Configuration > Program Types.
    """
    _name = "helpdesk.program.type"
    _description = "Helpdesk Program Type"
    _order = "name"

    name = fields.Char(string="Program Type", required=True)
    active = fields.Boolean(default=True)

    # clubs linked to this program type (res.partner records)
    # We do NOT store this as a relational field here — the link is
    # on res.partner.helpdesk_program_type_id (added below)
