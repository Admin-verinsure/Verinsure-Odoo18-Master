
from odoo import models, fields

class AutoReconcileLog(models.Model):
    _name = "auto.reconcile.log"
    _description = "Auto Reconciliation Log"

    date = fields.Datetime(default=fields.Datetime.now)
    matched = fields.Integer()
    ambiguous = fields.Integer()
    skipped = fields.Integer()
    no_partner = fields.Integer()
