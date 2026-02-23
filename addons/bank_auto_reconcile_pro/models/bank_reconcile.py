from odoo import models
from odoo.tools.float_utils import float_is_zero

class BankAutoReconcile(models.Model):
    _inherit = "account.bank.statement.line"

    def action_auto_reconcile(self):
        for line in self:

            if line.is_reconciled or not line.partner_id:
                continue

            open_moves = self.env["account.move.line"].search([
                ("partner_id", "=", line.partner_id.id),
                ("account_id.account_type", "in", ["asset_receivable", "liability_payable"]),
                ("reconciled", "=", False),
                ("move_id.state", "=", "posted"),
            ])

            for move_line in open_moves:

                residual = abs(move_line.amount_residual)
                amount = abs(line.amount)

                if float_is_zero(residual - amount, precision_rounding=move_line.currency_id.rounding):

                    payment_move = self.env["account.move"].create({
                        "move_type": "entry",
                        "journal_id": line.journal_id.id,
                        "date": line.date,
                        "line_ids": [
                            (0, 0, {
                                "account_id": line.journal_id.default_account_id.id,
                                "debit": amount if line.amount > 0 else 0.0,
                                "credit": amount if line.amount < 0 else 0.0,
                            }),
                            (0, 0, {
                                "account_id": move_line.account_id.id,
                                "partner_id": line.partner_id.id,
                                "credit": amount if line.amount > 0 else 0.0,
                                "debit": amount if line.amount < 0 else 0.0,
                            }),
                        ]
                    })

                    payment_move.action_post()

                    (move_line + payment_move.line_ids.filtered(
                        lambda l: l.account_id == move_line.account_id
                    )).reconcile()

                    break
