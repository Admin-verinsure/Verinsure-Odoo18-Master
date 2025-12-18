# -*- coding: utf-8 -*-

from odoo import api, fields, models


class EmployeeDetails(models.Model):
    """Compatibility shim.

    Some databases have an ir.rule on `employee.details` that references
    `partner_id`. If the base model doesn't define this field, *any* search on
    `employee.details` can crash with:

        ValueError: Invalid field employee.details.partner_id in leaf ...

    Adding the field here makes those rules valid again.
    """

    _inherit = "employee.details"

    partner_id = fields.Many2one(
        "res.partner",
        string="Related Partner",
        index=True,
        ondelete="set null",
        help="Optional link to a partner record (used by invoicing / access rules).",
    )
