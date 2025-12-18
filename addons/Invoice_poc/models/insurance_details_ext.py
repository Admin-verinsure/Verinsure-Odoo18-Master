from odoo import models, fields

class InsuranceDetails(models.Model):
    _inherit = "insurance.details"

    agent_id = fields.Many2one(
        "employee.details",
        string="Agent",
        ondelete="set null",
        index=True,
    )
