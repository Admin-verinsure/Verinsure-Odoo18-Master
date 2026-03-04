# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class AccountJournalAkahuExtend(models.Model):
    """
    Extends account.journal to expose a 'Fetch Transactions' button
    directly on the Accounting Dashboard journal kanban card.
    Only appears on journals that have an Akahu account linked.
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

    @api.depends('akahu_account_ids')
    def _compute_has_akahu(self):
        for journal in self:
            journal.has_akahu = bool(journal.akahu_account_ids)

    @api.depends('akahu_account_ids.last_synced')
    def _compute_akahu_last_synced(self):
        for journal in self:
            synced_dates = journal.akahu_account_ids.mapped('last_synced')
            journal.akahu_last_synced = max(synced_dates) if synced_dates else False

    def action_fetch_akahu_transactions(self):
        """Triggered by the Fetch Transactions button on the dashboard card."""
        self.ensure_one()
        engine = self.env['akahu.sync.engine']
        total_imported = 0

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

        for akahu_account in active_accounts:
            try:
                result = engine.sync_account(akahu_account)
                total_imported += result.get('imported', 0)
            except Exception as e:
                _logger.error("Akahu fetch failed for journal %s: %s", self.name, str(e))
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Sync Failed'),
                        'message': str(e),
                        'type': 'danger',
                        'sticky': True,
                    }
                }

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Transactions Fetched'),
                'message': _('%d new transaction(s) imported into %s.') % (
                    total_imported, self.name
                ),
                'type': 'success',
                'sticky': False,
            }
        }
