from odoo import models

class AutoReconcileEngine(models.Model):
    _name = "auto.reconcile.engine"
    _description = "Auto Reconcile Engine"

    def run_auto_reconcile(self, journal_id):
        journal = self.env['account.journal'].browse(journal_id)
        matched = 0

        lines = self.env['account.bank.statement.line'].search([
            ('journal_id','=',journal.id),
        ])

        for line in lines:
            if not line.partner_id or not line.move_id:
                continue

            liquidity = line.move_id.line_ids.filtered(
                lambda l: l.account_id == journal.default_account_id and not l.reconciled
            )
            if not liquidity:
                continue

            open_lines = self.env['account.move.line'].search([
                ('partner_id','=',line.partner_id.id),
                ('account_id.account_type','in',['asset_receivable','liability_payable']),
                ('reconciled','=',False),
                ('move_id.state','=','posted'),
            ])

            candidates = open_lines.filtered(
                lambda l: abs(l.amount_residual - abs(line.amount)) < 0.05
            )

            if len(candidates) == 1:
                (liquidity + candidates).reconcile()
                matched += 1

        return matched
