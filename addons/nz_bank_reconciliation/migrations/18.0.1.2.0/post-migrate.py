# -*- coding: utf-8 -*-
"""
Migration 18.0.1.2.0 — Encrypt existing plaintext tokens at rest (SEC-01).

On upgrade from <=1.1.0, app_token, app_secret, and user_token columns contain
plaintext values.  This post-migrate script reads each value, encrypts it with
AES-256-GCM using the module's _encrypt_token helper, and writes it back.

post-migrate runs AFTER the ORM has loaded the new model definitions, so we
can safely call the model's write() method which now encrypts automatically.

If a value is already a valid base64/GCM blob (i.e. starts with a nonce prefix
that is not a valid Akahu token prefix) we skip it — this makes the script
idempotent and safe to run on a fresh install.
"""
import logging
import base64

_logger = logging.getLogger(__name__)

_AKAHU_PLAINTEXT_PREFIXES = ('app_token_', 'user_token_', 'app_secret')


def _looks_like_plaintext(value):
    """Return True if the value appears to be an unencrypted Akahu token."""
    if not value:
        return False
    # Akahu tokens always start with known ASCII prefixes
    for prefix in _AKAHU_PLAINTEXT_PREFIXES:
        if value.startswith(prefix):
            return True
    # Anything not starting with a known prefix AND decodable as base64 with
    # length >= 28 bytes (12-byte nonce + 1-byte ct + 16-byte GCM tag) is
    # assumed already encrypted.
    try:
        raw = base64.b64decode(value)
        if len(raw) >= 28:
            return False
    except Exception:
        pass
    return True  # unknown format — try to encrypt defensively


def migrate(cr, version):
    if not version:
        return  # fresh install — tokens entered after install are auto-encrypted

    _logger.info('SEC-01 migration: encrypting existing plaintext tokens ...')

    # We use raw SQL for the reads but delegate writes to the ORM so the
    # model's write() hook applies encryption consistently.
    from odoo import registry, api, SUPERUSER_ID

    # Credentials: app_token + app_secret
    cr.execute("SELECT id, app_token, app_secret FROM akahu_credential")
    cred_rows = cr.fetchall()

    # Accounts: user_token
    cr.execute("SELECT id, user_token FROM akahu_account")
    acct_rows = cr.fetchall()

    if not cred_rows and not acct_rows:
        _logger.info('SEC-01 migration: no existing records to encrypt.')
        return

    # We need an Odoo env to call write() — use the registry trick standard
    # in Odoo migration scripts.
    with api.Environment.manage():
        env = api.Environment(cr, SUPERUSER_ID, {})

        for rec_id, app_token, app_secret in cred_rows:
            vals = {}
            if _looks_like_plaintext(app_token):
                vals['app_token'] = app_token
            if _looks_like_plaintext(app_secret):
                vals['app_secret'] = app_secret
            if vals:
                env['akahu.credential'].browse(rec_id).write(vals)
                _logger.info('SEC-01: encrypted credential id=%d', rec_id)

        for rec_id, user_token in acct_rows:
            if _looks_like_plaintext(user_token):
                env['akahu.account'].browse(rec_id).write({'user_token': user_token})
                _logger.info('SEC-01: encrypted akahu.account id=%d user_token', rec_id)

    _logger.info('SEC-01 migration: done.')
