from odoo import models
import requests

class AkahuEngine(models.Model):
    _name = "akahu.engine"
    _description = "Akahu Engine"

    def fetch_and_reconcile(self, journal_id, auto_reconcile=True):

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

        statement = self.env['account.bank.statement'].search([
            ('journal_id', '=', journal.id),
            ('state', '=', 'open')
        ], limit=1)

        if not statement:
            statement = self.env['account.bank.statement'].create({
                'journal_id': journal.id,
                'balance_start': 0.0,
                'balance_end_real': 0.0,
            })

        created_lines = []
        created = 0

        for tx in data.get("items", []):

            tx_id = tx.get("id")
            description = tx.get("description") or ""
            amount = tx.get("amount")

            existing = self.env['account.bank.statement.line'].search([
                ('akahu_transaction_id','=',tx_id)
            ], limit=1)

            if existing:
                continue

            # Partner detection (invoice based)
            partner_id = False
            invoice = self.env['account.move'].search([
                ('name','ilike',description),
                ('state','=','posted'),
                ('payment_state','!=','paid')
            ], limit=1)

            if invoice:
                partner_id = invoice.partner_id.id

            line = self.env['account.bank.statement.line'].create({
                'statement_id': statement.id,
                'journal_id': journal.id,
                'amount': amount,
                'payment_ref': tx_id,
                'partner_id': partner_id,
                'akahu_transaction_id': tx_id,
            })

            created_lines.append(line)
            created += 1

        # Ensure ORM state stable
        self.env.cr.flush()

        matched = 0

        if auto_reconcile:

            for line in created_lines:

                if not line.partner_id:
                    continue

                open_lines = self.env['account.move.line'].search([
                    ('partner_id','=',line.partner_id.id),
                    ('account_id.account_type','in',['asset_receivable','liability_payable']),
                    ('reconciled','=',False),
                    ('move_id.state','=','posted')
                ])

                candidates = open_lines.filtered(
                    lambda l: abs(l.amount_residual - abs(line.amount)) < 0.05
                )

                if len(candidates) == 1:
                    line.process_reconciliation({
                        'counterpart_aml_dicts': [{
                            'move_line': candidates.id,
                            'amount': abs(line.amount),
                        }]
                    })
                    matched += 1

        return {"created": created, "matched": matched}
