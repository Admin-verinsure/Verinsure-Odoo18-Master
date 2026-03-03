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

    Akahu transaction fields we use:
      _id           → akahu_transaction_id (stored on statement line to avoid duplicates)
      date          → date
      description   → payment_ref
      amount        → amount  (positive = credit to account, negative = debit)
      balance       → running balance (optional)
      meta.particulars / meta.code / meta.reference → appended to narration
      type          → transaction type label
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
        Skips transactions already imported (deduplication by akahu_transaction_id).
        Returns dict with 'imported' count.
        """
        cred = akahu_account.credential_id
        account_id = akahu_account.akahu_account_id

        if not account_id:
            # Refresh metadata first to get the Akahu account ID
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

        # Use cursor from last sync if available (incremental sync)
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
                # Mark account INACTIVE if auth failed
                if '401' in str(e) or '403' in str(e):
                    akahu_account.write({'akahu_status': 'INACTIVE'})
                raise

            items = data.get('items', [])
            all_transactions.extend(items)

            # Handle pagination cursor
            cursor = data.get('cursor', {})
            next_cursor = cursor.get('next') if cursor else None

            if not next_cursor:
                # Save the latest cursor for next incremental sync
                last_cursor = cursor.get('current') if cursor else None
                break
            else:
                params['cursor'] = next_cursor
                last_cursor = next_cursor

        _logger.info(
            'Akahu sync: fetched %d transactions across %d page(s) for %s',
            len(all_transactions), page_count, akahu_account.name
        )

        # ── Deduplication ──────────────────────────────────────────────────────
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
        Return set of akahu_transaction_id values already in this journal.
        We store the Akahu _id in the narration field with a prefix to allow
        deduplication without adding a custom field to account.bank.statement.line.

        Format stored: [akahu_id:trans_XXXXXXX]
        """
        self.env.cr.execute("""
            SELECT narration FROM account_bank_statement_line
            WHERE journal_id = %s
              AND narration LIKE '%%[akahu_id:trans_%%'
        """, (journal.id,))
        rows = self.env.cr.fetchall()
        ids = set()
        for (narration,) in rows:
            if narration:
                for part in narration.split('[akahu_id:'):
                    if ']' in part:
                        ids.add('trans_' + part.split(']')[0].replace('trans_', ''))
        return ids

    def _create_statement_lines(self, akahu_account, transactions):
        """
        Create account.bank.statement.line records for each transaction.
        Returns count of lines created.
        """
        BankLine = self.env['account.bank.statement.line'].sudo()
        journal = akahu_account.journal_id
        count = 0

        for tx in transactions:
            try:
                line_vals = self._map_transaction_to_statement_line(tx, journal, akahu_account)
                BankLine.create(line_vals)
                count += 1
            except Exception as e:
                _logger.warning(
                    'Failed to create statement line for tx %s: %s',
                    tx.get('_id'), str(e)
                )

        return count

    def _map_transaction_to_statement_line(self, tx, journal, akahu_account):
        """
        Map an Akahu transaction dict to account.bank.statement.line values.

        Akahu transaction structure:
        {
            "_id": "trans_...",
            "date": "2024-01-15T00:00:00.000Z",
            "description": "COUNTDOWN NEWTON 100",
            "amount": -45.50,         ← negative = money out, positive = money in
            "balance": 1234.56,
            "type": "CARD",
            "meta": {
                "particulars": "...",
                "code": "...",
                "reference": "...",
                "other_account": "01-1234-..."
            }
        }
        """
        tx_id = tx.get('_id', '')
        date_str = tx.get('date', '')
        description = tx.get('description') or tx.get('type') or _('Akahu Transaction')
        amount = float(tx.get('amount', 0.0))
        meta = tx.get('meta') or {}

        # Parse date (ISO 8601 → Odoo date)
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

        # Build narration with Akahu ID embedded for deduplication
        narration_parts = ['[akahu_id:%s]' % tx_id]
        other_acc = meta.get('other_account')
        if other_acc:
            narration_parts.append('Other account: %s' % other_acc)
        if tx.get('type'):
            narration_parts.append('Type: %s' % tx['type'])
        narration = ' | '.join(narration_parts)

        # FIX 3: Route to correct journal (credit card vs bank)
        resolved_journal = self._resolve_journal(tx, akahu_account)

        vals = {
            'journal_id': resolved_journal.id,
            'date': tx_date,
            'payment_ref': payment_ref[:255],
            'amount': amount,
            'narration': narration,
            'partner_name': meta.get('other_account', False) or False,
            'company_id': akahu_account.company_id.id,
        }

        # FIX 2: Multi-currency — store foreign currency if present in Akahu response
        # ASB returns conversion details for foreign-currency card transactions
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

    # ── FIX 3: Credit card journal routing ────────────────────────────────────
    CARD_TX_TYPES = {'CARD', 'EFTPOS', 'CREDIT_CARD'}

    def _resolve_journal(self, tx, akahu_account):
        """FIX 3: Route CARD/EFTPOS transactions to a credit card journal if one exists."""
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

