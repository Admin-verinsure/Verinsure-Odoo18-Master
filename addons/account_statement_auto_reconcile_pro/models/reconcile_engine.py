
from odoo import models, fields, api
from datetime import timedelta

class AutoReconcileEngine(models.Model):
    _name = "auto.reconcile.engine"
    _description = "Auto Reconcile Engine"

    @api.model
    def run_auto_reconcile(self):

        journals = self.env["account.journal"].search([
            ("type", "=", "bank"),
            ("auto_reconcile_enabled", "=", True)
        ])

        for journal in journals:

            matched = ambiguous = skipped = no_partner = 0

            since_date = fields.Date.today() - timedelta(days=journal.auto_reconcile_days)

            statement_lines = self.env["account.bank.statement.line"].search([
                ("journal_id", "=", journal.id),
                ("date", ">=", since_date),
                ("is_reconciled", "=", False),
            ])

            for line in statement_lines:

                if not line.partner_id:
                    no_partner += 1
                    continue

                liquidity_line = line.move_id.line_ids.filtered(
                    lambda l: l.account_id == journal.default_account_id
                )

                if not liquidity_line:
                    skipped += 1
                    continue

                open_lines = self.env["account.move.line"].search([
                    ("partner_id", "=", line.partner_id.id),
                    ("account_id.account_type", "in", ["asset_receivable", "liability_payable"]),
                    ("reconciled", "=", False),
                    ("move_id.state", "=", "posted"),
                    ("company_id", "=", line.company_id.id),
                ])

                candidates = open_lines.filtered(
                    lambda l: abs(l.amount_residual - abs(line.amount)) <= journal.auto_reconcile_tolerance
                )

                if len(candidates) == 1:
                    try:
                        (liquidity_line + candidates).reconcile()
                        matched += 1
                    except Exception:
                        skipped += 1
                elif len(candidates) > 1:
                    ambiguous += 1
                else:
                    skipped += 1

            self.env["auto.reconcile.log"].create({
                "matched": matched,
                "ambiguous": ambiguous,
                "skipped": skipped,
                "no_partner": no_partner,
            })
