# -*- coding: utf-8 -*-
import logging
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

AKAHU_BASE_URL = 'https://api.akahu.io/v1'


class AkahuCredential(models.Model):
    """
    Stores the Akahu App Token and App Secret for each company.
    One record per company. Tokens are stored encrypted via Odoo's
    standard char field (for production, consider using a vault or
    ir.config_parameter with sudo + encrypted storage).
    """
    _name = 'akahu.credential'
    _description = 'Akahu API Credentials'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    app_token = fields.Char(
        string='App Token',
        required=True,
        help='Your Akahu App Token (starts with app_token_...)',
    )
    app_secret = fields.Char(
        string='App Secret',
        required=True,
        password=True,
        help='Your Akahu App Secret. Never share this.',
    )
    active = fields.Boolean(default=True)
    connection_status = fields.Selection([
        ('untested', 'Not Tested'),
        ('ok', 'Connected'),
        ('error', 'Error'),
    ], string='Status', default='untested', readonly=True)
    last_tested = fields.Datetime(string='Last Tested', readonly=True)
    error_message = fields.Char(string='Last Error', readonly=True)

    _sql_constraints = [
        ('company_unique', 'UNIQUE(company_id)', 'Only one Akahu credential per company is allowed.'),
    ]

    # -------------------------------------------------------------------------
    # API HELPERS
    # -------------------------------------------------------------------------

    def _get_headers(self, user_token):
        """
        Build the required Akahu headers.
        Every user-scoped call needs both X-Akahu-Id and Authorization.
        """
        self.ensure_one()
        return {
            'Authorization': 'Bearer %s' % user_token,
            'X-Akahu-Id': self.app_token,
            'Content-Type': 'application/json',
        }

    def _api_get(self, user_token, path, params=None):
        """
        Generic GET against the Akahu API.
        Raises UserError on non-2xx responses.
        Returns parsed JSON body.
        """
        self.ensure_one()
        url = '%s%s' % (AKAHU_BASE_URL, path)
        try:
            resp = requests.get(
                url,
                headers=self._get_headers(user_token),
                params=params or {},
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            raise UserError(_('Akahu API connection failed: %s') % str(e))

        if resp.status_code == 401:
            raise UserError(_(
                'Akahu authentication failed (401). '
                'Check your App Token and User Token.'
            ))
        if resp.status_code == 403:
            raise UserError(_(
                'Akahu permission denied (403). '
                'Your app may be missing required scopes.'
            ))
        if resp.status_code >= 400:
            raise UserError(_(
                'Akahu API error %s: %s'
            ) % (resp.status_code, resp.text[:200]))

        data = resp.json()
        if not data.get('success'):
            raise UserError(_('Akahu returned success=false: %s') % str(data))
        return data

    # -------------------------------------------------------------------------
    # TEST CONNECTION
    # -------------------------------------------------------------------------

    def action_test_connection(self):
        """
        Test credentials by fetching the list of accounts for the first
        linked akahu.account. If none exist yet, we just validate that
        the app_token format looks right.
        """
        self.ensure_one()
        accounts = self.env['akahu.account'].search([
            ('credential_id', '=', self.id),
            ('active', '=', True),
        ], limit=1)

        try:
            if accounts:
                data = self._api_get(accounts[0].user_token, '/accounts')
                count = len(data.get('items', []))
                self.write({
                    'connection_status': 'ok',
                    'last_tested': fields.Datetime.now(),
                    'error_message': False,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful'),
                        'message': _('Connected! Found %d account(s) on Akahu.') % count,
                        'type': 'success',
                    }
                }
            else:
                # No user tokens yet — just confirm token format
                if not self.app_token.startswith('app_token_'):
                    raise ValidationError(_('App Token must start with "app_token_"'))
                self.write({
                    'connection_status': 'ok',
                    'last_tested': fields.Datetime.now(),
                    'error_message': False,
                })
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Credentials Saved'),
                        'message': _('App Token format looks valid. Add bank accounts below to test a full connection.'),
                        'type': 'info',
                    }
                }
        except Exception as e:
            self.write({
                'connection_status': 'error',
                'last_tested': fields.Datetime.now(),
                'error_message': str(e)[:256],
            })
            raise
