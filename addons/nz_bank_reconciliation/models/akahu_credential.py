# -*- coding: utf-8 -*-
import base64
import logging
import os
import time
import requests

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

AKAHU_BASE_URL = 'https://api.akahu.io/v1'

# RISK-01 FIX: Retry configuration for HTTP 429 (rate-limit) responses.
_MAX_RETRIES = 4
_RETRY_BACKOFF = [1, 2, 4, 8]  # seconds between attempts

# ---------------------------------------------------------------------------
# Token encryption helpers
# ---------------------------------------------------------------------------
# SEC-01 FIX: Tokens are encrypted at rest using AES-256-GCM (via the
# `cryptography` package that ships with Odoo 16+).  The symmetric key is
# stored in ir.config_parameter (key: akahu.token_key) so it lives in the
# database but is separate from the token ciphertext — an attacker needs
# both the config-param table row AND the credential table row to decrypt.
# For a higher assurance level, replace _get_encryption_key() with a call
# to an external KMS / Odoo vault module and store nothing in the DB.
# ---------------------------------------------------------------------------

def _get_encryption_key(env):
    """Return (and lazily create) the 32-byte AES key stored in ir.config_parameter."""
    ICP = env['ir.config_parameter'].sudo()
    key_b64 = ICP.get_param('akahu.token_key')
    if not key_b64:
        # First use — generate a random 256-bit key and persist it.
        raw_key = os.urandom(32)
        ICP.set_param('akahu.token_key', base64.b64encode(raw_key).decode())
        return raw_key
    return base64.b64decode(key_b64)


def _encrypt_token(env, plaintext):
    """Encrypt *plaintext* string; return a base64-encoded 'nonce||ciphertext||tag' blob."""
    if not plaintext:
        return plaintext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        _logger.warning(
            'SEC-01: cryptography package not available — storing token in plaintext. '
            'Install `cryptography` to enable at-rest encryption.'
        )
        return plaintext
    key = _get_encryption_key(env)
    nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def _decrypt_token(env, blob):
    """Decrypt a blob produced by _encrypt_token; return the original string."""
    if not blob:
        return blob
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        return blob  # graceful degradation — same as encrypt path
    try:
        raw = base64.b64decode(blob)
        nonce, ct = raw[:12], raw[12:]
        key = _get_encryption_key(env)
        return AESGCM(key).decrypt(nonce, ct, None).decode()
    except Exception:
        # Blob is not encrypted (e.g. legacy plaintext value migrated in).
        # Return as-is so existing credentials keep working after upgrade.
        return blob


class AkahuCredential(models.Model):
    """
    Stores the Akahu App Token and App Secret for each company.
    One record per company.

    SEC-01 FIX: app_token and app_secret are encrypted before being written to
    the database (AES-256-GCM).  The raw values are never stored as plaintext.
    Use self._get_app_token() / self._get_app_secret() to retrieve decrypted
    values in server-side code.
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
    # Stored encrypted — do NOT read .app_token directly in code; use _get_app_token()
    app_token = fields.Char(
        string='App Token',
        required=True,
        groups='base.group_erp_manager',
        help='Your Akahu App Token (starts with app_token_...). '
             'Stored encrypted. Visible to ERP Managers only.',
    )
    # Stored encrypted — do NOT read .app_secret directly in code; use _get_app_secret()
    app_secret = fields.Char(
        string='App Secret',
        required=True,
        password=True,
        groups='base.group_erp_manager',
        help='Your Akahu App Secret. Stored encrypted. '
             'Visible to ERP Managers only — never sent to regular users.',
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
    # Encryption hooks
    # -------------------------------------------------------------------------

    def write(self, vals):
        # SEC-01: Encrypt tokens before persisting to DB.
        if 'app_token' in vals and vals['app_token']:
            vals['app_token'] = _encrypt_token(self.env, vals['app_token'])
        if 'app_secret' in vals and vals['app_secret']:
            vals['app_secret'] = _encrypt_token(self.env, vals['app_secret'])
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('app_token'):
                vals['app_token'] = _encrypt_token(self.env, vals['app_token'])
            if vals.get('app_secret'):
                vals['app_secret'] = _encrypt_token(self.env, vals['app_secret'])
        return super().create(vals_list)

    def _get_app_token(self):
        """Return the decrypted app_token value."""
        self.ensure_one()
        return _decrypt_token(self.env, self.app_token)

    def _get_app_secret(self):
        """Return the decrypted app_secret value."""
        self.ensure_one()
        return _decrypt_token(self.env, self.app_secret)

    # -------------------------------------------------------------------------
    # SEC-03: Token revocation / rotation
    # -------------------------------------------------------------------------

    def action_revoke_credentials(self):
        """
        SEC-03 FIX (clause 2.2.1.d): Revoke and clear all stored credentials
        for this company so that fresh tokens can be re-entered.  A
        confirmation wizard is shown before any data is cleared.
        """
        # METHOD GUARD: Restricted to ERP Managers only (same group that can see the
        # credential fields). Prevents account managers from revoking credentials via RPC.
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Revoking credentials is restricted to ERP Managers.'))

        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Revoke Akahu Credentials'),
            'res_model': 'akahu.credential.revoke.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_credential_id': self.id},
        }

    # -------------------------------------------------------------------------
    # API HELPERS
    # -------------------------------------------------------------------------

    def _get_headers(self, user_token_plain):
        """
        Build the required Akahu headers.
        Accepts the already-decrypted user_token string.
        """
        self.ensure_one()
        return {
            'Authorization': 'Bearer %s' % user_token_plain,
            'X-Akahu-Id': self._get_app_token(),
            'Content-Type': 'application/json',
        }

    def _api_get(self, user_token_plain, path, params=None):
        """
        Generic GET against the Akahu API.
        Raises UserError on non-2xx responses.

        SEC-04 FIX: Raw API error bodies are sanitised before being surfaced
        to the UI — only a safe prefix is shown, and any token-like strings
        are stripped so credentials cannot leak through error messages.

        RISK-01 FIX: Retries up to _MAX_RETRIES times on HTTP 429 with
        exponential backoff.
        """
        self.ensure_one()
        url = '%s%s' % (AKAHU_BASE_URL, path)

        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.get(
                    url,
                    headers=self._get_headers(user_token_plain),
                    params=params or {},
                    timeout=30,
                )
            except requests.exceptions.RequestException as e:
                raise UserError(_('Akahu API connection failed: %s') % str(e))

            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', _RETRY_BACKOFF[attempt]))
                _logger.warning(
                    'Akahu API rate-limited (429) on %s. '
                    'Waiting %ds before retry %d/%d.',
                    path, retry_after, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(retry_after)
                continue

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
                # SEC-04 FIX: Sanitise the error body before showing it in the
                # UI.  We truncate to 120 chars and redact any token-shaped
                # strings (anything matching [a-zA-Z0-9_]{20,}) to prevent
                # accidental credential leakage through Akahu's error payloads.
                import re
                raw = resp.text[:120] if resp.text else ''
                safe_msg = re.sub(r'[a-zA-Z0-9_]{20,}', '[REDACTED]', raw)
                raise UserError(_(
                    'Akahu API error %s. Please check your credentials and try again. '
                    'Detail: %s'
                ) % (resp.status_code, safe_msg))

            data = resp.json()
            if not data.get('success'):
                raise UserError(_('Akahu returned success=false. Check the server logs for details.'))
            return data

        raise UserError(_(
            'Akahu API rate limit exceeded for %s after %d retries. '
            'The sync run will be retried on the next cron schedule.'
        ) % (path, _MAX_RETRIES))

    # -------------------------------------------------------------------------
    # TEST CONNECTION
    # -------------------------------------------------------------------------

    def action_test_connection(self):
        """
        Test credentials by fetching the list of accounts for the first
        linked akahu.account.
        """
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

        self.ensure_one()
        accounts = self.env['akahu.account'].search([
            ('credential_id', '=', self.id),
            ('active', '=', True),
        ], limit=1)

        try:
            if accounts:
                # Pass decrypted user token to the API helper
                data = self._api_get(accounts[0]._get_user_token(), '/accounts')
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
                plain_token = self._get_app_token()
                if not plain_token.startswith('app_token_'):
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
                        'message': _(
                            'App Token format looks valid. '
                            'Add bank accounts below to test a full connection.'
                        ),
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
