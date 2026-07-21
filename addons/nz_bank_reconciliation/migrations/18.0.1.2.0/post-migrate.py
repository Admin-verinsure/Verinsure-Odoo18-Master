# -*- coding: utf-8 -*-
"""
Migration 18.0.1.2.0 — Encrypt existing plaintext tokens at rest (SEC-01).

On upgrade from <=1.1.0, app_token, app_secret, and user_token columns contain
plaintext values.  This post-migrate script reads each value, encrypts it with
AES-256-GCM using the module's _encrypt_token helper, and writes it back.

post-migrate runs AFTER the ORM has loaded the new model definitions, so we
can safely call the model's write() method which now encrypts automatically.

VNZ-13 FIX: "already encrypted?" is now a check for the 'gcm1:' marker prefix
that _encrypt_token() writes (see models/akahu_credential.py), not a guess
based on base64 validity / byte length. The previous heuristic could
misclassify a plaintext App Secret as already-encrypted and skip it.
"""
import logging

_logger = logging.getLogger(__name__)

_CIPHERTEXT_MARKER = 'gcm1:'


def _looks_like_plaintext(value):
    """Return True if the value has not yet been through _encrypt_token()."""
    if not value:
        return False
    return not value.startswith(_CIPHERTEXT_MARKER)


def migrate(cr, version):
    if not version:
        return  # fresh install — tokens entered after install are auto-encrypted

    _logger.info('SEC-01 migration: encrypting existing plaintext tokens ...')

    # We use raw SQL for the reads but delegate writes to the ORM so the
    # model's write() hook applies encryption consistently.
    from odoo import api, SUPERUSER_ID

    # Credentials: app_token + app_secret
    cr.execute("SELECT id, app_token, app_secret FROM akahu_credential")
    cred_rows = cr.fetchall()

    # Accounts: user_token
    cr.execute("SELECT id, user_token FROM akahu_account")
    acct_rows = cr.fetchall()

    if not cred_rows and not acct_rows:
        _logger.info('SEC-01 migration: no existing records to encrypt.')
        return

    # VNZ-04 FIX: api.Environment.manage() was removed in Odoo 17.0 and does
    # not exist on Odoo 18 — the old `with api.Environment.manage():` block
    # raised AttributeError here, aborting the migration BEFORE any token was
    # encrypted. api.Environment(cr, SUPERUSER_ID, {}) is the correct
    # Odoo 18 idiom and needs no context manager.
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
