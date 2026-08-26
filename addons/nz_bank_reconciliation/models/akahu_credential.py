# -*- coding: utf-8 -*-
import base64
import binascii
import logging
import os
import time
import requests
from pathlib import Path
from urllib.parse import urlencode

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import config as odoo_config
from ..utils.log_redaction import sanitize_log_value

_logger = logging.getLogger(__name__)

# VNZ-19 FIX: shared redaction helper so every place that stores/returns
# error text uses the same denylist consistently. This is defense-in-depth,
# not the primary control (secrets are never intentionally echoed back) —
# the denylist can still miss a secret with unusual characters or under 20
# chars, so this narrows exposure rather than eliminating it.
import re as _re


def _redact_secret(text):
    if not text:
        return text
    return _re.sub(r'[a-zA-Z0-9_]{20,}', '[REDACTED]', text)


AKAHU_BASE_URL = 'https://api.akahu.io/v1'

# RISK-01 FIX: Retry configuration for HTTP 429 (rate-limit) responses.
_MAX_RETRIES = 4
_RETRY_BACKOFF = [1, 2, 4, 8]  # seconds between attempts

# ---------------------------------------------------------------------------
# Token encryption helpers
# ---------------------------------------------------------------------------
# SEC-01 FIX: Tokens are encrypted at rest using AES-256-GCM (via the
# `cryptography` package that ships with Odoo 16+). The symmetric key is
# sourced from AKAHU_TOKEN_KEY (if set) or from an instance-local key file
# under Odoo's data_dir. It is never stored in PostgreSQL.
# ---------------------------------------------------------------------------

def _get_encryption_key(env):
    """Return the 32-byte AES key used to encrypt/decrypt tokens.

    VNZ-06 FIX: encryption-at-rest must survive a database compromise.
    Priority: (1) AKAHU_TOKEN_KEY env var, (2) instance-local key file.
    The key is never persisted in PostgreSQL.
    """
    env_key_b64 = os.environ.get('AKAHU_TOKEN_KEY')
    if env_key_b64:
        key = _decode_key_material(env_key_b64, source_label='AKAHU_TOKEN_KEY')
    else:
        key = _read_or_create_file_key()

    # One-time migration path for installations that still carry the
    # historical database-stored key. We only use it to re-encrypt existing
    # ciphertext and immediately remove it from ir.config_parameter.
    _migrate_legacy_db_key(env, key)
    return key


# VNZ-13 FIX: an explicit version marker on every ciphertext blob so
# "is this value already encrypted?" is a prefix check, not a guess based on
# byte length/shape. Previously a plaintext App Secret that happened to be
# valid base64 of 28+ bytes was silently classified as "already encrypted"
# and left in plaintext (see migration script).
_CIPHERTEXT_MARKER = 'gcm1:'

_LEGACY_PLAINTEXT_PARAM_KEYS = (
    'akahu.access_token',
    'akahu.api_key',
    'akahu.app_id',
    'akahu.account_id',
    'akahu.user_id',
)
_LEGACY_PLAINTEXT_CLEANUP_DONE_KEY = 'akahu.legacy_plaintext_cleanup_done'

_KEY_FILE_NAME = 'akahu_token.key'
_KEY_FILE_DIR = 'nz_bank_reconciliation'


def _get_key_file_path():
    data_dir = odoo_config.get('data_dir')
    if not data_dir:
        raise UserError(_(
            'Odoo data_dir is not configured. Configure data_dir so the '
            'Akahu encryption key file can be stored outside PostgreSQL.'
        ))
    return Path(data_dir) / _KEY_FILE_DIR / _KEY_FILE_NAME


def _decode_key_material(raw_key_b64, source_label='encryption key'):
    try:
        if isinstance(raw_key_b64, str):
            raw_key_b64 = raw_key_b64.encode()
        key = base64.urlsafe_b64decode(raw_key_b64)
    except (binascii.Error, ValueError, TypeError):
        raise UserError(_(
            'The Akahu %s is invalid. It must be a base64-encoded 32-byte key.'
        ) % source_label)

    if len(key) != 32:
        raise UserError(_(
            'The Akahu %s has invalid length. It must decode to exactly '
            '32 bytes for AES-256-GCM.'
        ) % source_label)
    return key


def _read_or_create_file_key():
    key_path = _get_key_file_path()
    if key_path.exists():
        try:
            key_b64 = key_path.read_bytes().strip()
        except OSError as e:
            raise UserError(_(
                'Cannot read Akahu encryption key file at %s: %s'
            ) % (str(key_path), str(e)))

        try:
            key = _decode_key_material(key_b64, source_label='key file')
        except UserError:
            raise UserError(_(
                'The Akahu key file at %s is invalid or corrupt. Restore the '
                'original key file from backup, or set AKAHU_TOKEN_KEY to the '
                'original key value used to encrypt existing tokens.'
            ) % str(key_path))
        try:
            os.chmod(str(key_path), 0o600)
        except OSError:
            # Non-POSIX filesystems may not support chmod semantics.
            pass
        return key

    key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from cryptography.fernet import Fernet
        key_b64 = Fernet.generate_key()
    except Exception:
        # Fallback preserves the same 32-byte key size expected by AES-256-GCM.
        key_b64 = base64.urlsafe_b64encode(os.urandom(32))

    try:
        with open(key_path, 'xb') as fp:
            fp.write(key_b64)
            fp.write(b'\n')
        os.chmod(str(key_path), 0o600)
    except FileExistsError:
        # Race-safe: another worker created the key file first.
        key_b64 = key_path.read_bytes().strip()
    except OSError as e:
        raise UserError(_(
            'Cannot create Akahu encryption key file at %s: %s'
        ) % (str(key_path), str(e)))

    return _decode_key_material(key_b64, source_label='key file')


def _encrypt_token_with_key(plaintext, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)  # 96-bit nonce recommended for GCM
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return _CIPHERTEXT_MARKER + base64.b64encode(nonce + ct).decode()


def _decrypt_token_with_key(blob, key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    payload = blob[len(_CIPHERTEXT_MARKER):]
    raw = base64.b64decode(payload)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


def _migrate_legacy_db_key(env, active_key):
    """One-time migration: re-encrypt ciphertext from legacy DB key to active key."""
    ICP = env['ir.config_parameter'].sudo()

    def _has_verified_encrypted_credentials():
        has_encrypted_app_token = bool(
            env['akahu.credential'].sudo().search([
                ('app_token', '=like', _CIPHERTEXT_MARKER + '%'),
            ], limit=1)
        )

        has_encrypted_user_token = bool(
            env['akahu.account'].sudo().search([
                ('user_token', '=like', _CIPHERTEXT_MARKER + '%'),
            ], limit=1)
        )

        return has_encrypted_app_token and has_encrypted_user_token

    def _cleanup_legacy_plaintext_params():
        if ICP.get_param(_LEGACY_PLAINTEXT_CLEANUP_DONE_KEY) == '1':
            return

        legacy_params = ICP.search([('key', 'in', list(_LEGACY_PLAINTEXT_PARAM_KEYS))])
        if not legacy_params:
            ICP.set_param(_LEGACY_PLAINTEXT_CLEANUP_DONE_KEY, '1')
            return

        if not _has_verified_encrypted_credentials():
            return

        legacy_params.unlink()
        ICP.set_param(_LEGACY_PLAINTEXT_CLEANUP_DONE_KEY, '1')
        _logger.info('Removed obsolete plaintext configuration.')

    legacy_b64 = ICP.get_param('akahu.token_key')

    if legacy_b64:
        legacy_key = _decode_key_material(legacy_b64, source_label='legacy database key')

        def _rewrite_table(table, fields_to_process):
            select_cols = ', '.join(['id'] + fields_to_process)
            env.cr.execute('SELECT %s FROM %s' % (select_cols, table))
            rows = env.cr.fetchall()
            for row in rows:
                rec_id = row[0]
                updates = {}
                for idx, field_name in enumerate(fields_to_process, start=1):
                    value = row[idx]
                    if not value or not value.startswith(_CIPHERTEXT_MARKER):
                        continue
                    try:
                        plain = _decrypt_token_with_key(value, legacy_key)
                    except Exception:
                        # Already migrated or encrypted with a different key.
                        continue
                    updates[field_name] = _encrypt_token_with_key(plain, active_key)

                if updates:
                    set_sql = ', '.join('%s = %%s' % k for k in updates.keys())
                    params = list(updates.values()) + [rec_id]
                    env.cr.execute(
                        'UPDATE %s SET %s WHERE id = %%s' % (table, set_sql),
                        params,
                    )

        _rewrite_table('akahu_credential', ['app_token', 'app_secret'])
        _rewrite_table('akahu_account', ['user_token'])
        ICP.search([('key', '=', 'akahu.token_key')]).unlink()
        _logger.info('Migrated legacy Akahu credentials.')

    _cleanup_legacy_plaintext_params()


def _encrypt_token(env, plaintext):
    """Encrypt *plaintext* string; return a marker-prefixed base64 'nonce||ciphertext||tag' blob."""
    if not plaintext:
        return plaintext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        _logger.error(
            'SEC-01: cryptography package not available — refusing to store token plaintext.'
        )
        raise UserError(_(
            'Cannot store Akahu credentials because the required encryption '
            'library is not installed on this server. Contact your administrator.'
        ))
    key = _get_encryption_key(env)
    return _encrypt_token_with_key(plaintext, key)


def _decrypt_token(env, blob):
    """Decrypt a blob produced by _encrypt_token; return the original string."""
    if not blob:
        return blob
    if not blob.startswith(_CIPHERTEXT_MARKER):
        # No marker: legacy plaintext value that predates SEC-01, or the
        # `cryptography` package was unavailable at write time. Return as-is
        # so existing credentials keep working after upgrade.
        return blob
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        # VNZ-12 FIX: this is a real error state (we have a marked ciphertext
        # but can't decrypt it), not a legacy-plaintext case — fail closed
        # instead of returning the raw ciphertext blob as if it were a token.
        _logger.error('SEC-01: cryptography package not available — cannot decrypt stored token.')
        raise UserError(_(
            'Cannot decrypt the stored Akahu token: the required encryption '
            'library is not installed on this server. Contact your administrator.'
        ))
    payload = blob[len(_CIPHERTEXT_MARKER):]
    try:
        key = _get_encryption_key(env)
        return _decrypt_token_with_key(_CIPHERTEXT_MARKER + payload, key)
    except Exception:
        # VNZ-12 FIX: previously this silently returned the raw ciphertext
        # blob, which was then sent to Akahu as a bearer token (a confusing
        # 401 instead of a clear error). Fail closed with a clear message —
        # this happens when the encryption key changed/was reset.
        _logger.error('SEC-01: failed to decrypt stored token — encryption key may have changed.')
        raise UserError(_(
            'Cannot decrypt the stored Akahu token. This usually means the '
            'server\'s encryption key was reset or changed. Please re-enter '
            'the App Token / App Secret / User Token to fix this.'
        ))


class AkahuCredential(models.Model):
    """
    Stores the Akahu App Token and User Access Token for each company.
    One record per company.

    SEC-01 FIX: sensitive tokens are encrypted before being written to the
    database (AES-256-GCM). The raw values are never stored as plaintext.
    Use token getter helpers to retrieve decrypted values in server-side code.
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
    # Stored encrypted — do NOT read .user_access_token directly in code;
    # use _get_user_access_token()
    user_access_token = fields.Char(
        string='User Access Token',
        groups='base.group_erp_manager',
        help='Akahu User Access Token (user_token_...). Stored encrypted. '
             'Visible to ERP Managers only.',
    )
    # Legacy field retained for backward compatibility with existing databases.
    # New flow uses user_access_token instead.
    app_secret = fields.Char(
        string='App Secret (Legacy)',
        required=False,
        # VNZ-11 FIX: `password=True` is not a valid Char field parameter in
        # this Odoo version (it was silently ignored, logging an install
        # warning, and did NOT mask the field). Masking is now applied at
        # the view level with widget="password" instead — see
        # views/akahu_credential_views.xml.
        groups='base.group_erp_manager',
        help='Your Akahu App Secret. Stored encrypted. '
             'Visible to ERP Managers only — never sent to regular users.',
    )
    oauth_redirect_uri = fields.Char(
        string='OAuth Redirect URI',
        groups='base.group_erp_manager',
        help='Registered Akahu OAuth callback URI. Must exactly match the URI configured in Akahu.',
    )

    active = fields.Boolean(default=True)
    connection_status = fields.Selection([
        ('untested', 'Not Tested'),
        ('ok', 'Connected'),
        ('error', 'Error'),
    ], string='Status', default='untested', readonly=True)
    last_tested = fields.Datetime(string='Last Tested', readonly=True)
    error_message = fields.Char(string='Last Error', readonly=True)
    has_credentials = fields.Boolean(
        compute='_compute_has_credential_flags',
    )
    has_app_token = fields.Boolean(
        compute='_compute_has_credential_flags',
    )
    has_user_token = fields.Boolean(
        compute='_compute_has_credential_flags',
    )

    _sql_constraints = [
        ('company_unique', 'UNIQUE(company_id)', 'Only one Akahu credential per company is allowed.'),
    ]

    @api.depends('app_token', 'user_access_token')
    def _compute_has_credential_flags(self):
        for rec in self:
            rec.has_app_token = bool(rec.app_token)
            rec.has_user_token = bool(rec.user_access_token)
            rec.has_credentials = bool(rec.app_token and rec.user_access_token)

    # -------------------------------------------------------------------------
    # Encryption hooks
    # -------------------------------------------------------------------------

    def write(self, vals):
        # SEC-01: Encrypt tokens before persisting to DB.
        if 'app_token' in vals and vals['app_token']:
            vals['app_token'] = _encrypt_token(self.env, vals['app_token'])
        if 'user_access_token' in vals and vals['user_access_token']:
            vals['user_access_token'] = _encrypt_token(self.env, vals['user_access_token'])
        if 'app_secret' in vals and vals['app_secret']:
            vals['app_secret'] = _encrypt_token(self.env, vals['app_secret'])
        return super().write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('app_token'):
                vals['app_token'] = _encrypt_token(self.env, vals['app_token'])
            if vals.get('user_access_token'):
                vals['user_access_token'] = _encrypt_token(self.env, vals['user_access_token'])
            if vals.get('app_secret'):
                vals['app_secret'] = _encrypt_token(self.env, vals['app_secret'])
        return super().create(vals_list)

    def unlink(self):
        # VNZ-03 FIX: the ACL now only grants unlink to base.group_erp_manager
        # (see security/ir.model.access.csv), but this explicit guard is kept
        # as defense-in-depth so the "can destroy, cannot restore" gap cannot
        # reopen from a future ACL edit alone. Deleting a credential while
        # bank accounts still reference it is blocked at the DB level too
        # (see akahu.account.credential_id, now ondelete='restrict').
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_(
                'Deleting Akahu credentials is restricted to ERP Managers. '
                'Use Revoke Credentials to clear tokens instead.'
            ))
        return super().unlink()

    def _get_app_token(self):
        """Return the decrypted app_token value."""
        self.ensure_one()
        cred = self.sudo()
        return _decrypt_token(cred.env, cred.app_token)

    def _get_app_secret(self):
        """Return the decrypted app_secret value."""
        self.ensure_one()
        cred = self.sudo()
        return _decrypt_token(cred.env, cred.app_secret)

    def _get_user_access_token(self):
        """Return the decrypted user access token value."""
        self.ensure_one()
        cred = self.sudo()
        return _decrypt_token(cred.env, cred.user_access_token)

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

    def action_open_replace_credentials_wizard(self):
        """Open wizard to replace stored App Token and App Secret."""
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Replacing credentials is restricted to ERP Managers.'))

        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Replace Akahu Credentials'),
            'res_model': 'akahu.credential.replace.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_credential_id': self.id},
        }

    def action_connect_akahu_oauth(self):
        """Start the server-side Akahu OAuth flow."""
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Connecting Akahu is restricted to ERP Managers.'))

        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/nz_bank_reconciliation/akahu/oauth/start/%s' % self.id,
            'target': 'self',
        }

    def _build_oauth_authorization_url(self, state, redirect_uri=None):
        self.ensure_one()
        app_token = self._get_app_token()
        app_secret = self._get_app_secret()
        redirect_uri = redirect_uri or self.oauth_redirect_uri
        if not app_token:
            raise ValidationError(_('App Token is required before connecting Akahu.'))
        if not app_secret:
            raise ValidationError(_('App Secret is required before connecting Akahu.'))
        if not redirect_uri:
            raise ValidationError(_('OAuth Redirect URI is required before connecting Akahu.'))

        params = {
            'response_type': 'code',
            'client_id': app_token,
            'redirect_uri': redirect_uri,
            'scope': 'ENDURING_CONSENT',
            'state': state,
        }
        return 'https://oauth.akahu.nz?%s' % urlencode(params)

    def _exchange_oauth_code(self, authorization_code, redirect_uri=None):
        self.ensure_one()
        if not authorization_code:
            raise ValidationError(_('Missing Akahu authorization code.'))

        redirect_uri = redirect_uri or self.oauth_redirect_uri
        if not redirect_uri:
            raise ValidationError(_('OAuth Redirect URI is required before exchanging the code.'))
        app_secret = self._get_app_secret()
        if not app_secret:
            raise ValidationError(_('App Secret is required before exchanging the code.'))

        payload = {
            'grant_type': 'authorization_code',
            'code': authorization_code,
            'redirect_uri': redirect_uri,
            'client_id': self._get_app_token(),
            'client_secret': app_secret,
        }
        try:
            resp = requests.post(
                'https://api.akahu.io/v1/token',
                data=payload,
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            raise UserError(_('Akahu token exchange failed: %s') % str(e))

        if resp.status_code >= 400:
            raw = resp.text[:120] if resp.text else ''
            safe_msg = _redact_secret(raw)
            raise UserError(_(
                'Akahu token exchange failed with HTTP %s. Detail: %s'
            ) % (resp.status_code, safe_msg))

        try:
            data = resp.json()
        except ValueError:
            raise UserError(_('Akahu token exchange returned a non-JSON response.'))

        access_token = data.get('access_token') or data.get('token') or data.get('user_token')
        if not access_token:
            raise UserError(_('Akahu token exchange did not return a user access token.'))
        return access_token

    def _fetch_oauth_accounts(self, user_access_token):
        self.ensure_one()
        data = self._api_get(user_access_token, '/accounts')
        return data.get('items', [])

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

    def _api_request(self, user_token_plain, path, method='GET', params=None, json_body=None):
        """
        Generic Akahu API request helper with shared auth/retry/error handling.
        Returns parsed JSON response (or {'success': True} for empty 2xx responses).
        """
        self.ensure_one()
        url = '%s%s' % (AKAHU_BASE_URL, path)
        method = (method or 'GET').upper()

        for attempt in range(_MAX_RETRIES):
            try:
                resp = requests.request(
                    method,
                    url,
                    headers=self._get_headers(user_token_plain),
                    params=params or {},
                    json=json_body,
                    timeout=30,
                )
            except requests.exceptions.RequestException as e:
                raise UserError(_('Akahu API connection failed: %s') % str(e))

            if resp.status_code == 429:
                retry_after = int(resp.headers.get('Retry-After', _RETRY_BACKOFF[attempt]))
                _logger.warning(
                    'Akahu API rate-limited (429) on %s %s. '
                    'Waiting %ds before retry %d/%d.',
                    sanitize_log_value(method),
                    sanitize_log_value(path),
                    sanitize_log_value(retry_after),
                    sanitize_log_value(attempt + 1),
                    sanitize_log_value(_MAX_RETRIES),
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
                raw = resp.text[:120] if resp.text else ''
                safe_msg = _redact_secret(raw)
                raise UserError(_(
                    'Akahu API error %s. Please check your credentials and try again. '
                    'Detail: %s'
                ) % (resp.status_code, safe_msg))

            if not resp.text:
                return {'success': True}

            try:
                data = resp.json()
            except ValueError:
                raise UserError(_('Akahu API returned a non-JSON success response.'))

            if not data.get('success'):
                raise UserError(_('Akahu returned success=false. Check the server logs for details.'))
            return data

        raise UserError(_(
            'Akahu API rate limit exceeded for %s %s after %d retries. '
            'The operation will be retried later.'
        ) % (method, path, _MAX_RETRIES))

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
                    sanitize_log_value(path),
                    sanitize_log_value(retry_after),
                    sanitize_log_value(attempt + 1),
                    sanitize_log_value(_MAX_RETRIES),
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
                # strings via the shared _redact_secret() helper (VNZ-19) to
                # prevent accidental credential leakage through Akahu's error
                # payloads.
                raw = resp.text[:120] if resp.text else ''
                safe_msg = _redact_secret(raw)
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
        Validate credentials against Akahu using app token + user access token.
        This test does not depend on bank account records.
        """
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

        self.ensure_one()
        try:
            plain_token = self._get_app_token()
            user_token = self._get_user_access_token()
            if not plain_token:
                raise ValidationError(_('App Token is required.'))
            if not user_token:
                raise ValidationError(_('User Access Token is required.'))
            if not plain_token.startswith('app_token_'):
                raise ValidationError(_('App Token must start with "app_token_"'))

            data = self._api_get(user_token, '/accounts')
            count = len(data.get('items', []))
            message = _('Connected! Found %d account(s) on Akahu.') % count
            notif_type = 'success'
            status = 'ok'

            self.write({
                'connection_status': status,
                'last_tested': fields.Datetime.now(),
                'error_message': False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': message,
                    'type': notif_type,
                }
            }
        except Exception as e:
            # VNZ-19 FIX: this write bypassed _redact_secret() entirely,
            # unlike the _api_get() error path above — a raw exception
            # string (which can echo back request/response content) was
            # stored as-is. Apply the same redaction helper for consistency.
            self.write({
                'connection_status': 'error',
                'last_tested': fields.Datetime.now(),
                'error_message': _redact_secret(str(e)[:256]),
            })
            raise
