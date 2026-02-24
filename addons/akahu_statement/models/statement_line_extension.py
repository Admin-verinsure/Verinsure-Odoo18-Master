from odoo import models, fields

class StatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    akahu_transaction_id = fields.Char(index=True)
