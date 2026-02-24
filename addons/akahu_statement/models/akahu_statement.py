from odoo import models, fields
import requests

class AkahuStatement(models.Model):
    _name = "akahu.statement.engine"
    _description = "Akahu Statement Engine"

    def fetch_and_reconcile(self, journal_id, days=90):

        journal = self.env['account.journal'].browse(journal_id)
        params = self.env['ir.config_parameter'].sudo()

        access_token = params.get_param('akahu.access_token')
        account_id = params.get_param('akahu.account_id')
        base_url = params.get_param('akahu.base_url')
        app_id = params.get_param('akahu.app_id')

        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Akahu-Id": app_id,
            "Content-Type": "application/json"
        }

        response = requests.get(
            f"{base_url}/transactions?account={account_id}",
            headers=headers,
            timeout=30
        )

        data = response.json()

        created = 0
        matched = 0

        for tx in data.get("items", []):

            tx_id = tx.get("id")
            description = tx.get("description") or ""
            amount = tx.get("amount")

            existing = self.env['account.bank.statement.line'].search([
                ('payment_ref','=',tx_id)
            ], limit=1)

            if existing:
                continue

            # -------- SMART PARTNER DETECTION --------
            partner_id = False
            invoice = self.env['account.move'].search([
                ('name','ilike',description),
                ('state','=','posted'),
                ('payment_state','!=','paid')
            ], limit=1)

            if invoice:
                partner_id = invoice.partner_id.id
            else:
                open_line = self.env['account.move.line'].search([
                    ('account_id.account_type','in',['asset_receivable','liability_payable']),
                    ('reconciled','=',False),
                    ('move_id.state','=','posted'),
                    ('amount_residual','=',abs(amount))
                ], limit=1)
                if open_line:
                    partner_id = open_line.partner_id.id

            # -------- CREATE STATEMENT LINE --------
            statement_line = self.env['account.bank.statement.line'].create({
                'journal_id': journal.id,
                'amount': amount,
                'payment_ref': tx_id,
                'partner_id': partner_id,
            })

            created += 1

            # -------- ENSURE POSTED --------
            if statement_line.move_id and statement_line.move_id.state == 'draft':
                statement_line.move_id.action_post()

            # -------- RECONCILIATION --------
            if partner_id and statement_line.move_id:

                liquidity = statement_line.move_id.line_ids.filtered(
                    lambda l: l.account_id == journal.default_account_id and not l.reconciled
                )

                open_lines = self.env['account.move.line'].search([
                    ('partner_id','=',partner_id),
                    ('account_id.account_type','in',['asset_receivable','liability_payable']),
                    ('reconciled','=',False),
                    ('move_id.state','=','posted')
                ])

                candidates = open_lines.filtered(
                    lambda l: abs(l.amount_residual - abs(amount)) < 0.05
                )

                if len(candidates) == 1:
                    (liquidity + candidates).reconcile()
                    matched += 1

        return {"created": created, "matched": matched}
