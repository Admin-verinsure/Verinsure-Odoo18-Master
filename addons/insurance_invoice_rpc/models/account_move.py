# -*- coding: utf-8 -*-
from odoo import fields, models

class AccountMove(models.Model):
    _inherit = "account.move"

    insurance_details_id = fields.Many2one(
        "insurance.details",
        string="Insurance (RPC Link)",
        index=True,
        ondelete="cascade",
    )
