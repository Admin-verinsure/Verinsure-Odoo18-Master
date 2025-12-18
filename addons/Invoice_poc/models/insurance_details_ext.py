# -*- coding: utf-8 -*-
from odoo import models, fields

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    # NOTE: keep x_ prefix to avoid confusion with Studio/manual-field conventions.
    x_agent_id = fields.Many2one(
        comodel_name="employee.details",
        string="Agent",
        ondelete="set null",
        index=True,
    )
