# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from .akahu_credential import _encrypt_token, _decrypt_token

_logger = logging.getLogger(__name__)


class AkahuAccount(models.Model):
    """
    Represents one connected bank account in Akahu.
    Each account has its own User Access Token (user_token_...)
    and maps to an Odoo journal (bank account).

    SEC-01 FIX: user_token is encrypted at rest via AES-256-GCM.
    Use self._get_user_token() in server-side code — never read
    self.user_token directly and pass it to an API call.

    BUG FIX (multi-account): action_refresh_account_info() now raises
    a clear error when a user token maps to more than one Akahu account
    and no akahu_account_id is set yet, instead of silently picking
    items[0].
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
    # SEC-01 FIX: stored encrypted — use _get_user_token() to read
    user_token = fields.Char(
        string='User Access Token',
        required=True,
        password=True,
        groups='base.group_erp_manager',
        help='The Akahu User Access Token (user_token_...) for this bank account. '
             'Stored encrypted. Visible to ERP Managers only.',
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

    sync_cursor = fields.Char(
        string='Sync Cursor',
        readonly=True,
        help='Akahu pagination cursor. Used internally — do not edit.',
    )

    _sql_constraints = [
        (
            'journal_unique',
            'UNIQUE(journal_id)',
            'Each Odoo journal can only be linked to one Akahu bank account. '
            'Please choose a different journal or edit the existing account.',
        ),
    ]

    # ── Encryption hooks ──────────────────────────────────────────────────────

    def write(self, vals):
        # SEC-01: Encrypt user_token before persisting to the database.
        if 'user_token' in vals and vals['user_token']:
            vals['user_token'] = _encrypt_token(self.env, vals['user_token'])
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('user_token'):
                vals['user_token'] = _encrypt_token(self.env, vals['user_token'])
        return super().create(vals_list)

    def _get_user_token(self):
        """Return the decrypted user_token value. Always use this in code."""
        self.ensure_one()
        return _decrypt_token(self.env, self.user_token)

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
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))


        BUG FIX (multi-account): When no akahu_account_id is stored yet and
        the user token grants access to more than one Akahu account, we now
        raise a descriptive error listing the available account IDs rather
        than silently picking items[0].  The admin must set akahu_account_id
        manually (or via a future selection wizard) before the first sync.
        """
        self.ensure_one()
        cred = self.credential_id
        try:
            data = cred._api_get(self._get_user_token(), '/accounts')
        except Exception as e:
            raise UserError(_('Failed to fetch Akahu accounts: %s') % str(e))

        items = data.get('items', [])
        matched = None

        if self.akahu_account_id:
            # Known ID — find exact match
            matched = next((i for i in items if i.get('_id') == self.akahu_account_id), None)
            if not matched:
                raise UserError(_(
                    'Akahu account ID "%s" was not found in the response from Akahu. '
                    'The account may have been disconnected.'
                ) % self.akahu_account_id)
        else:
            # First-time resolution
            if len(items) == 0:
                raise UserError(_('No accounts found for this User Token on Akahu.'))
            if len(items) == 1:
                # Unambiguous — safe to auto-select
                matched = items[0]
            else:
                # BUG FIX: Multiple accounts — refuse to pick arbitrarily.
                # List available IDs so the admin can set the correct one.
                available = ', '.join(
                    '%s (%s)' % (i.get('_id', '?'), i.get('name', '?'))
                    for i in items
                )
                raise UserError(_(
                    'This User Token grants access to %d Akahu accounts:\n\n%s\n\n'
                    'Please enter the correct "Akahu Account ID" (acc_...) in the '
                    '"Akahu Account ID" field, then refresh again.'
                ) % (len(items), available))

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
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

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
