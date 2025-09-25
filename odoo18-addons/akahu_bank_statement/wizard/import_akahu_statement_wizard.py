from odoo import models, fields, api
import requests
from datetime import datetime
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)

class AkahuImportWizard(models.TransientModel):
    _name = 'akahu.import.wizard'
    _description = 'Import Akahu Bank Transactions'

    journal_id = fields.Many2one('account.journal', string="Bank Journal", required=True, default=lambda self: self.env['account.journal'].search([('type', '=', 'bank')], limit=1))

    def action_import_transactions(self):
        access_token = self.env['ir.config_parameter'].sudo().get_param('akahu.access_token')
        account_id = self.env['ir.config_parameter'].sudo().get_param('akahu.account_id')
        base_url = self.env['ir.config_parameter'].sudo().get_param('akahu.base_url')
        app_token = self.env['ir.config_parameter'].sudo().get_param('akahu.api_key')

        headers = {
            'Authorization': f'Bearer {access_token}',
            'X-Akahu-Id': app_token,
            'Accept': 'application/json',
        }

        response = requests.get(f'{base_url}/transactions?account={account_id}', headers=headers)
        _logger.info("Akahu API raw response: %s", response.text)
        
        if response.status_code != 200:
            raise UserError(f"Failed to fetch transactions: {response.status_code} - {response.text}")
        transactions = response.json().get('items', [])

        if not transactions:
            _logger.info("No transactions found from Akahu API")
            return


        # Create statement
        statement = self.env['account.bank.statement'].create({
            'name': 'Akahu Import',
            'journal_id': self.journal_id.id,
            'date': fields.Date.today(),
        })

        for tx in transactions:
            amount = tx.get('amount')
            date = tx.get('date')
            description = tx.get('description')

            self.env['account.bank.statement.line'].create({
                'statement_id': statement.id,
                'amount': amount,
                'date': date.split("T")[0],
                'name': description or 'Akahu Transaction',
                'journal_id': self.journal_id.id,
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.bank.statement',
            'view_mode': 'form',
            'res_id': statement.id,
        }
