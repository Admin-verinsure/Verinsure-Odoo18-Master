# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AkahuAccount(models.Model):
    """
    Represents one connected bank account in Akahu.
    Each account has its own User Access Token (user_token_...)
    and maps to an Odoo journal (bank account).

    Key fields from Akahu /accounts response:
      _id             → akahu_account_id
      name            → akahu_account_name
      formatted_account → akahu_formatted_account
      status          → akahu_status  (ACTIVE / INACTIVE)
      balance.available → balance_available
      connection.name → bank_name
      refreshed.transactions → last_refreshed
    """
    _name = 'akahu.account'
    _description = 'Akahu Connected Bank Account'
    _order = 'company_id, bank_name, akahu_account_name'

    # ── Odoo-side fields ──────────────────────────────────────────────────────
    name = fields.Char(
        string='Account Label',
        compute='_compute_name',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    credential_id = fields.Many2one(
        'akahu.credential',
        string='Akahu Credentials',
        required=True,
        domain="[('company_id', '=', company_id)]",
        ondelete='cascade',
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Odoo Bank Journal',
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
        required=True,
        help='Transactions from this Akahu account will be imported into this journal.',
    )
    active = fields.Boolean(default=True)

    # ── Akahu-side fields ─────────────────────────────────────────────────────
    user_token = fields.Char(
        string='User Access Token',
        required=True,
        password=True,
        help='The Akahu User Access Token (user_token_...) for this bank account.',
    )
    akahu_account_id = fields.Char(
        string='Akahu Account ID',
        readonly=True,
        help='Populated automatically after first sync (acc_...)',
    )
    akahu_account_name = fields.Char(string='Account Name (Akahu)', readonly=True)
    akahu_formatted_account = fields.Char(string='Bank Account Number', readonly=True)
    bank_name = fields.Char(string='Bank / Institution', readonly=True)
    akahu_status = fields.Selection([
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('UNKNOWN', 'Unknown'),
    ], string='Akahu Status', default='UNKNOWN', readonly=True)
    balance_available = fields.Float(string='Available Balance (NZD)', readonly=True)
    last_refreshed = fields.Datetime(string='Last Refreshed by Akahu', readonly=True)
    last_synced = fields.Datetime(string='Last Synced to Odoo', readonly=True)

    # Cursor for paginated transaction sync — stores the last cursor.next value
    sync_cursor = fields.Char(
        string='Sync Cursor',
        readonly=True,
        help='Akahu pagination cursor. Used internally — do not edit.',
    )

    # ── Computed ──────────────────────────────────────────────────────────────
    @api.depends('bank_name', 'akahu_account_name', 'akahu_formatted_account')
    def _compute_name(self):
        for rec in self:
            parts = [
                rec.bank_name or '',
                rec.akahu_account_name or '',
                rec.akahu_formatted_account or '',
            ]
            rec.name = ' — '.join(p for p in parts if p) or _('New Account')

    def _is_inactive_warning(self):
        return self.akahu_status == 'INACTIVE'

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_refresh_account_info(self):
        """
        Calls GET /accounts and updates account metadata & status.
        Also used to detect INACTIVE accounts.
        """
        self.ensure_one()
        cred = self.credential_id
        try:
            data = cred._api_get(self.user_token, '/accounts')
        except Exception as e:
            raise UserError(_('Failed to fetch Akahu accounts: %s') % str(e))

        # Find the matching account in the response (match by akahu_account_id if known)
        items = data.get('items', [])
        matched = None
        if self.akahu_account_id:
            matched = next((i for i in items if i.get('_id') == self.akahu_account_id), None)
        if not matched and items:
            # First time — pick the first account returned for this user token
            matched = items[0]

        if not matched:
            raise UserError(_('No accounts found for this User Token on Akahu.'))

        vals = {
            'akahu_account_id': matched.get('_id'),
            'akahu_account_name': matched.get('name'),
            'akahu_formatted_account': matched.get('formatted_account'),
            'bank_name': matched.get('connection', {}).get('name'),
            'akahu_status': matched.get('status', 'UNKNOWN'),
            'balance_available': matched.get('balance', {}).get('available', 0.0),
        }
        refreshed_ts = matched.get('refreshed', {}).get('transactions')
        if refreshed_ts:
            vals['last_refreshed'] = fields.Datetime.from_string(
                refreshed_ts.replace('T', ' ').split('.')[0]
            )
        self.write(vals)

        status_msg = '✅ Active' if vals['akahu_status'] == 'ACTIVE' else '⚠️ INACTIVE — reconnection required!'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Account Info Refreshed'),
                'message': '%s | %s | Status: %s' % (
                    vals['bank_name'], vals['akahu_formatted_account'], status_msg
                ),
                'type': 'success' if vals['akahu_status'] == 'ACTIVE' else 'warning',
                'sticky': vals['akahu_status'] == 'INACTIVE',
            }
        }

    def action_sync_transactions(self):
        """Manual trigger to sync transactions for this account."""
        self.ensure_one()
        engine = self.env['akahu.sync.engine']
        result = engine.sync_account(self)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sync Complete'),
                'message': _('%d new transaction(s) imported for %s.') % (
                    result.get('imported', 0), self.name
                ),
                'type': 'success',
            }
        }
