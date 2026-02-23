
from odoo import models, fields

class AccountJournal(models.Model):
    _inherit = "account.journal"

    auto_reconcile_enabled = fields.Boolean(string="Enable Auto Reconciliation")
    auto_reconcile_days = fields.Integer(default=7)
    auto_reconcile_tolerance = fields.Float(default=0.05)
