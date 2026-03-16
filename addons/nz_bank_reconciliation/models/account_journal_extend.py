# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class AccountJournalAkahuExtend(models.Model):
    """
    Extends account.journal to expose a 'Fetch Transactions' button
    directly on the Accounting Dashboard journal kanban card.

    Full flow on button click:
      1. Fetch new transactions from Akahu (deduplicated — no copies)
      2. Create bank statement lines in Odoo
      3. Immediately run auto-reconciliation for this company
      4. Show single notification with fetch + reconcile counts
    """
    _inherit = 'account.journal'

    akahu_account_ids = fields.One2many(
        'akahu.account',
        'journal_id',
        string='Akahu Accounts',
    )
    has_akahu = fields.Boolean(
        string='Has Akahu Integration',
        compute='_compute_has_akahu',
        store=False,
    )
    akahu_last_synced = fields.Datetime(
        string='Last Akahu Sync',
        compute='_compute_akahu_last_synced',
        store=False,
    )

    akahu_bank_feeds_disabled = fields.Boolean(
        string='Bank Feeds Disabled (Akahu)',
        compute='_compute_akahu_bank_feeds_disabled',
        store=False,
        help='True when this journal has an active Akahu account configured, '
             'which disables the default Odoo Bank Feeds option.',
    )

    def _AccountJournal__get_bank_statements_available_sources(self):
        """
        Override the private name-mangled method used by bank_statements_source.
        In Odoo 18, the field selection chain is:
          bank_statements_source
            → _get_bank_statements_available_sources()   (public, calls private)
              → __get_bank_statements_available_sources() (private, name-mangled to
                 _AccountJournal__get_bank_statements_available_sources)
        Other modules (account_accountant etc.) override the private one.
        We must use the mangled name to properly call super() and extend the list.
        """
        sources = super()._AccountJournal__get_bank_statements_available_sources()
        akahu_option = ('akahu', 'Akahu (NZ Open Banking)')
        if akahu_option not in sources:
            sources.append(akahu_option)
        return sources

    @api.depends('akahu_account_ids')
    def _compute_has_akahu(self):
        for journal in self:
            journal.has_akahu = bool(journal.akahu_account_ids)

    @api.depends('akahu_account_ids', 'akahu_account_ids.active', 'akahu_account_ids.akahu_status')
    def _compute_akahu_bank_feeds_disabled(self):
        for journal in self:
            active_accounts = journal.akahu_account_ids.filtered(
                lambda a: a.active and a.akahu_status != 'INACTIVE'
            )
            journal.akahu_bank_feeds_disabled = bool(active_accounts)

    @api.depends('akahu_account_ids.last_synced')
    def _compute_akahu_last_synced(self):
        for journal in self:
            synced_dates = journal.akahu_account_ids.mapped('last_synced')
            journal.akahu_last_synced = max(synced_dates) if synced_dates else False

    def action_configure_akahu_account(self):
        """
        Opens the Akahu Bank Account configuration form/list filtered to this journal.
        - If an Akahu account already exists for this journal → open it directly in form view.
        - If none exists → open a new form pre-filled with this journal.
        Triggered by the 'Configure Bank Account' button on the journal kanban card.
        """
        self.ensure_one()
        existing = self.akahu_account_ids[:1]

        if existing:
            # Open the existing akahu.account record in form view
            return {
                'type': 'ir.actions.act_window',
                'name': _('Akahu Bank Account'),
                'res_model': 'akahu.account',
                'view_mode': 'form',
                'res_id': existing.id,
                'target': 'current',
            }
        else:
            # Open a new form pre-filled with this journal
            return {
                'type': 'ir.actions.act_window',
                'name': _('Configure Akahu Bank Account'),
                'res_model': 'akahu.account',
                'view_mode': 'form',
                'target': 'current',
                'context': {
                    'default_journal_id': self.id,
                    'default_company_id': self.company_id.id,
                },
            }

    def action_fetch_akahu_transactions(self):
        """
        Triggered by the Fetch Transactions button on the accounting dashboard card.

        Step 1 — Sync: pulls new transactions from Akahu into bank statement lines.
                        Deduplication via cursor ensures no copies of existing lines.
        Step 2 — Reconcile: immediately runs auto-reconciliation for this company
                        so newly fetched transactions are matched right away.
        """
        self.ensure_one()
        sync_engine = self.env['akahu.sync.engine']
        recon_engine = self.env['auto.reconciliation.engine']

        # ── Guard: must have active Akahu account linked ───────────────────────
        active_accounts = self.akahu_account_ids.filtered(
            lambda a: a.active and a.akahu_status != 'INACTIVE'
        )
        if not active_accounts:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Active Akahu Accounts'),
                    'message': _(
                        'No active Akahu accounts linked to this journal. '
                        'Go to Accounting → Configuration → Akahu Bank Accounts to set one up.'
                    ),
                    'type': 'warning',
                    'sticky': False,
                }
            }

        # ── Step 1: Fetch transactions from Akahu ──────────────────────────────
        total_imported = 0
        company_ids_synced = set()

        for akahu_account in active_accounts:
            try:
                result = sync_engine.sync_account(akahu_account)
                total_imported += result.get('imported', 0)
                company_ids_synced.add(akahu_account.company_id.id)
                _logger.info(
                    "Akahu fetch: %d new transactions for journal %s (company: %s)",
                    result.get('imported', 0),
                    self.name,
                    akahu_account.company_id.name,
                )
            except Exception as e:
                _logger.error("Akahu fetch failed for journal %s: %s", self.name, str(e))
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Fetch Failed'),
                        'message': str(e),
                        'type': 'danger',
                        'sticky': True,
                    }
                }

        # ── Step 2: Auto-reconcile immediately for affected companies ──────────
        # Only run if we actually imported something new — no point reconciling
        # if nothing changed.
        total_reconciled = 0
        if total_imported > 0 and company_ids_synced:
            try:
                recon_results = recon_engine.run_all(
                    company_ids=list(company_ids_synced),
                    preview_mode=False,
                )
                for company_id, result in recon_results.items():
                    if 'error' not in result:
                        total_reconciled += sum(
                            result.get(k, {}).get('matched_count', 0)
                            for k in [
                                'bank_statement',
                                'customer_payment',
                                'vendor_payment',
                                'intercompany',
                            ]
                        )
                _logger.info(
                    "Auto-reconciliation after fetch: %d matches for journal %s",
                    total_reconciled, self.name,
                )
            except Exception as e:
                # Reconciliation failure is non-fatal — transactions were still imported
                _logger.warning(
                    "Auto-reconciliation failed after fetch for journal %s: %s",
                    self.name, str(e)
                )
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Fetched — Reconciliation Warning'),
                        'message': _(
                            '%d transaction(s) imported into %s. '
                            'Auto-reconciliation could not complete: %s'
                        ) % (total_imported, self.name, str(e)),
                        'type': 'warning',
                        'sticky': True,
                    }
                }

        # ── Build result notification ──────────────────────────────────────────
        if total_imported == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Already Up to Date'),
                    'message': _('No new transactions found for %s.') % self.name,
                    'type': 'info',
                    'sticky': False,
                }
            }

        if total_reconciled > 0:
            message = _(
                '%d new transaction(s) imported and %d match(es) reconciled automatically for %s.'
            ) % (total_imported, total_reconciled, self.name)
        else:
            message = _(
                '%d new transaction(s) imported for %s. '
                'No automatic matches found — manual reconciliation may be needed.'
            ) % (total_imported, self.name)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Fetch & Reconcile Complete'),
                'message': message,
                'type': 'success',
                'sticky': False,
            }
        }
