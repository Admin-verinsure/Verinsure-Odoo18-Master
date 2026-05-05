# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timezone
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AkahuSyncEngine(models.Model):
    """
    Core sync engine. Pulls transactions from Akahu and creates
    account.bank.statement.line records in Odoo for reconciliation.

    Odoo 18 deduplication: uses unique_import_id column (built-in).
    No custom narration/memo embedding needed.
    """
    _name = 'akahu.sync.engine'
    _description = 'Akahu Sync Engine'

    # ── PUBLIC ENTRY POINTS ────────────────────────────────────────────────────

    @api.model
    def cron_sync_all(self):
        """Called by scheduled cron — syncs all active ACTIVE accounts."""
        _logger.info('Akahu Sync Cron: Starting')
        accounts = self.env['akahu.account'].sudo().search([
            ('active', '=', True),
            ('akahu_status', '!=', 'INACTIVE'),
            ('credential_id.active', '=', True),
        ])
        total_imported = 0
        for account in accounts:
            try:
                result = self.sync_account(account)
                total_imported += result.get('imported', 0)
            except Exception as e:
                _logger.error('Akahu sync failed for account %s: %s', account.name, str(e))
                self.env['akahu.sync.log'].sudo().create({
                    'akahu_account_id': account.id,
                    'company_id': account.company_id.id,
                    'status': 'error',
                    'transactions_imported': 0,
                    'error_message': str(e)[:512],
                })
        _logger.info('Akahu Sync Cron: Done. Total imported: %d', total_imported)

    @api.model
    def sync_account(self, akahu_account):
        """
        Sync one Akahu account → Odoo bank statement lines.
        Handles pagination with cursor.
        Deduplication via unique_import_id (Odoo 18 native column).
        Returns dict with 'imported' count.
        """
        cred = akahu_account.credential_id
        account_id = akahu_account.akahu_account_id

        if not account_id:
            akahu_account.action_refresh_account_info()
            account_id = akahu_account.akahu_account_id

        if not account_id:
            raise UserError(_('Could not determine Akahu Account ID for %s') % akahu_account.name)

        if akahu_account.akahu_status == 'INACTIVE':
            raise UserError(_(
                'Account %s is INACTIVE on Akahu. '
                'The user must reconnect via the Akahu OAuth flow.'
            ) % akahu_account.name)

        # ── Paginated fetch ────────────────────────────────────────────────────
        path = '/accounts/%s/transactions' % account_id
        all_transactions = []
        params = {}

        if akahu_account.sync_cursor:
            params['cursor'] = akahu_account.sync_cursor

        last_cursor = None
        page_count = 0

        while True:
            page_count += 1
            _logger.info(
                'Akahu sync: fetching page %d for account %s (cursor: %s)',
                page_count, akahu_account.name, params.get('cursor', 'none')
            )
            try:
                data = cred._api_get(akahu_account.user_token, path, params=params)
            except UserError as e:
                if '401' in str(e) or '403' in str(e):
                    akahu_account.write({'akahu_status': 'INACTIVE'})
                raise

            items = data.get('items', [])
            all_transactions.extend(items)

            cursor = data.get('cursor', {})
            next_cursor = cursor.get('next') if cursor else None

            if not next_cursor:
                last_cursor = cursor.get('current') if cursor else None
                break
            else:
                params['cursor'] = next_cursor
                last_cursor = next_cursor

        _logger.info(
            'Akahu sync: fetched %d transactions across %d page(s) for %s',
            len(all_transactions), page_count, akahu_account.name
        )

        # ── Deduplication via unique_import_id ────────────────────────────────
        existing_ids = self._get_existing_akahu_ids(akahu_account.journal_id)
        new_transactions = [
            t for t in all_transactions
            if t.get('_id') and t['_id'] not in existing_ids
        ]

        _logger.info(
            'Akahu sync: %d new (of %d total) for %s',
            len(new_transactions), len(all_transactions), akahu_account.name
        )

        # ── Create bank statement lines ────────────────────────────────────────
        imported = 0
        if new_transactions:
            imported = self._create_statement_lines(akahu_account, new_transactions)

        # ── Update account metadata ────────────────────────────────────────────
        akahu_account.write({
            'last_synced': fields.Datetime.now(),
            'sync_cursor': last_cursor or akahu_account.sync_cursor,
        })

        # ── Write sync log ─────────────────────────────────────────────────────
        self.env['akahu.sync.log'].sudo().create({
            'akahu_account_id': akahu_account.id,
            'company_id': akahu_account.company_id.id,
            'status': 'success',
            'transactions_fetched': len(all_transactions),
            'transactions_imported': imported,
        })

        return {'imported': imported, 'fetched': len(all_transactions)}

    # ── HELPERS ────────────────────────────────────────────────────────────────

    def _get_existing_akahu_ids(self, journal):
        """
        Odoo 18 uses unique_import_id for deduplication — a native column
        on account_bank_statement_line. We store the Akahu _id there directly.
        """
        self.env.cr.execute("""
            SELECT unique_import_id FROM account_bank_statement_line
            WHERE journal_id = %s
              AND unique_import_id LIKE 'akahu-%%'
        """, (journal.id,))
        rows = self.env.cr.fetchall()
        # Strip the 'akahu-' prefix to get back the raw Akahu _id
        return {row[0].replace('akahu-', '', 1) for row in rows if row[0]}

    def _create_statement_lines(self, akahu_account, transactions):
        """
        Create account.bank.statement.line records for each transaction.
        Returns count of lines created.
        """
        BankLine = self.env['account.bank.statement.line'].sudo()
        count = 0

        for tx in transactions:
            try:
                line_vals = self._map_transaction_to_statement_line(tx, akahu_account)
                BankLine.create(line_vals)
                count += 1
            except Exception as e:
                _logger.warning(
                    'Failed to create statement line for tx %s: %s',
                    tx.get('_id'), str(e)
                )

        return count

    def _map_transaction_to_statement_line(self, tx, akahu_account):
        """
        Map an Akahu transaction dict to account.bank.statement.line values.

        Odoo 18 schema used:
          unique_import_id  → 'akahu-{tx._id}'  (deduplication)
          payment_ref       → description + meta fields
          amount            → transaction amount
          partner_name      → other_account from meta
          transaction_type  → Akahu tx type (CARD, TRANSFER etc.)
          foreign_currency_id / amount_currency → for USD/AUD transactions
        """
        tx_id = tx.get('_id', '')
        date_str = tx.get('date', '')
        description = tx.get('description') or tx.get('type') or _('Akahu Transaction')
        amount = float(tx.get('amount', 0.0))
        meta = tx.get('meta') or {}

        # Parse date
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            tx_date = dt.date()
        except Exception:
            tx_date = fields.Date.today()

        # Build payment_ref from description + meta fields
        ref_parts = [description]
        for key in ['particulars', 'code', 'reference']:
            val = meta.get(key)
            if val and val.strip():
                ref_parts.append(val.strip())
        payment_ref = ' | '.join(ref_parts)

        # Route to correct journal (credit card vs bank)
        resolved_journal = self._resolve_journal(tx, akahu_account)

        vals = {
            'journal_id': resolved_journal.id,
            'date': tx_date,
            'payment_ref': payment_ref[:255],
            'amount': amount,
            'partner_name': meta.get('other_account') or False,
            'transaction_type': tx.get('type') or False,
            'company_id': akahu_account.company_id.id,
            # Odoo 18 native deduplication field — prefix with 'akahu-' to namespace it
            'unique_import_id': 'akahu-%s' % tx_id,
        }

        # Multi-currency: ASB returns conversion details for foreign card transactions
        # tx.meta.conversion = {"amount": -42.50, "currency": "USD", "rate": 0.6516}
        conversion = meta.get('conversion') or {}
        foreign_currency_code = conversion.get('currency')
        foreign_amount = conversion.get('amount')
        if foreign_currency_code and foreign_amount is not None:
            foreign_currency = self.env['res.currency'].sudo().search(
                [('name', '=', foreign_currency_code.upper())], limit=1
            )
            if foreign_currency:
                vals['foreign_currency_id'] = foreign_currency.id
                vals['amount_currency'] = float(foreign_amount)

        return vals

    # ── Credit card journal routing ────────────────────────────────────────────
    CARD_TX_TYPES = {'CARD', 'EFTPOS', 'CREDIT_CARD'}

    def _resolve_journal(self, tx, akahu_account):
        """Route CARD/EFTPOS transactions to a credit card journal if one exists."""
        tx_type = (tx.get('type') or '').upper()
        if tx_type in self.CARD_TX_TYPES:
            cc_journal = self.env['account.journal'].sudo().search([
                ('company_id', '=', akahu_account.company_id.id),
                ('type', '=', 'bank'),
                ('name', 'ilike', 'credit'),
            ], limit=1)
            if cc_journal:
                return cc_journal
        return akahu_account.journal_id
