import requests
from odoo import models, fields, api
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class AkahuBankStatement(models.Model):
    _name = 'akahu.bank.statement'
    _description = 'Akahu Bank Statement Import'

    @api.model
    def import_akahu_transactions(self):
        # Get token
        akahu_token = self.env['ir.config_parameter'].sudo().get_param('akahu.access_token')
        if not akahu_token:
            _logger.error("Akahu access token not found in system parameters!")
            return

        # Get journal ID
        journal_id_param = self.env['ir.config_parameter'].sudo().get_param('akahu.journal_id')
        if not journal_id_param:
            _logger.error("Akahu journal_id not set in system parameters!")
            return

        try:
            journal_id = int(journal_id_param)
        except ValueError:
            _logger.error("Invalid journal_id format in system parameters!")
            return

        headers = {
            "Authorization": f"Bearer {akahu_token}"
        }

        # Step 1: Get Accounts
        accounts_url = "https://api.akahu.io/v1/accounts"
        accounts = requests.get(accounts_url, headers=headers).json().get("items", [])

        for acc in accounts:
            acc_id = acc["_id"]
            transactions_url = f"https://api.akahu.io/v1/accounts/{acc_id}/transactions"
            since_date = (datetime.now() - timedelta(days=90)).isoformat()

            res = requests.get(transactions_url, headers=headers, params={'start': since_date})
            transactions = res.json().get("items", [])

            for tx in transactions:
                self.env['account.bank.statement.line'].create({
                    'date': tx.get("date"),
                    'payment_ref': tx.get("description") or 'Akahu',
                    'amount': tx.get("amount"),
                    'partner_name': tx.get("counterparty", {}).get("name", "Unknown"),
                    'journal_id': journal_id,
                })

    def debug_akahu_api(self):
        akahu_token = self.env['ir.config_parameter'].sudo().get_param('akahu.access_token')

        if not akahu_token:
            _logger.error("Akahu access token not set in system parameters!")
            return

        headers = {
            "Authorization": f"Bearer {akahu_token}"
        }

        try:
            user_response = requests.get("https://api.akahu.io/v1/me", headers=headers)
            user_info = user_response.json()
            _logger.info(f"Akahu User Info: {user_info}")

            acc_response = requests.get("https://api.akahu.io/v1/accounts", headers=headers)
            accounts = acc_response.json().get("items", [])

            for acc in accounts:
                _logger.info(f"Akahu Account: {acc.get('name')} - ID: {acc.get('_id')}")

        except Exception as e:
            _logger.error(f"Error fetching Akahu API data: {str(e)}")
