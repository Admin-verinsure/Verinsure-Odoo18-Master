from odoo import models, fields

class AccountJournal(models.Model):
    _inherit = "account.journal"

    akahu_enabled = fields.Boolean("Enable Akahu")
    akahu_app_token = fields.Char("Akahu App Token")
    akahu_account_id = fields.Char("Akahu Account ID")

    auto_reconcile_enabled = fields.Boolean("Enable Auto Reconciliation")
    auto_reconcile_days = fields.Integer(default=7)
    auto_reconcile_tolerance = fields.Float(default=0.05)
