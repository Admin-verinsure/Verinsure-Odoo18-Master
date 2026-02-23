from odoo import models, fields

class AutoReconcileLog(models.Model):
    _name = "auto.reconcile.log"
    _description = "Auto Reconcile Log"

    date = fields.Datetime(default=fields.Datetime.now)
    created = fields.Integer()
    matched = fields.Integer()
    skipped = fields.Integer()
