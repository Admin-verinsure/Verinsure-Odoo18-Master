from odoo import models, fields
import requests

class AkahuImportWizard(models.TransientModel):
    _name = "akahu.import.wizard"
    _description = "Import Akahu Transactions"

    journal_id = fields.Many2one(
        'account.journal',
        domain="[('type','=','bank')]",
        required=True
    )
    days_to_fetch = fields.Integer(default=90)
    auto_reconcile = fields.Boolean(default=True)

    def action_import(self):
        self.ensure_one()

        params = self.env['ir.config_parameter'].sudo()
        access_token = params.get_param('akahu.access_token')
        account_id = params.get_param('akahu.account_id')
        base_url = params.get_param('akahu.base_url')

        headers = {
            "Authorization": access_token,
            "Content-Type": "application/json"
        }

        created = 0
        skipped = 0

        try:
            response = requests.get(
                f"{base_url}/transactions?account={account_id}",
                headers=headers,
                timeout=20
            )
            data = response.json()

            for tx in data.get("items", []):
                tx_id = tx.get("id")
                amount = tx.get("amount")

                existing = self.env['account.bank.statement.line'].search([
                    ('payment_ref','=',tx_id)
                ], limit=1)

                if existing:
                    skipped += 1
                    continue

                self.env['account.bank.statement.line'].create({
                    'journal_id': self.journal_id.id,
                    'amount': amount,
                    'payment_ref': tx_id,
                })

                created += 1

        except Exception:
            pass

        matched = 0
        if self.auto_reconcile:
            matched = self.env['auto.reconcile.engine'].run_auto_reconcile(
                self.journal_id.id
            )

        self.env['auto.reconcile.log'].create({
            'created': created,
            'matched': matched,
            'skipped': skipped,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Akahu Import Completed',
                'message': f'Created: {created}, Matched: {matched}, Skipped: {skipped}',
                'type': 'success',
            }
        }
