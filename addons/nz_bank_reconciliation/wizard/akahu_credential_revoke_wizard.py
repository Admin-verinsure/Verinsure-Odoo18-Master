# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class AkahuCredentialRevokeWizard(models.TransientModel):
    """
    SEC-03 FIX (SOW clause 2.2.1.d): Confirmation step for revoking /
    rotating a compromised Akahu credential set.

    Workflow:
      1. Admin opens the wizard from the credential form view.
      2. Wizard shows what will be cleared and asks for explicit confirmation.
      3. On confirm: app_token, app_secret, and all linked user_tokens are
         wiped.  The credential record moves to 'untested' status so the
         admin must re-enter fresh tokens before sync can resume.

    This satisfies the "revoke and re-enter" requirement without requiring an
    active call to Akahu (the token may already be compromised / invalid).
    """
    _name = 'akahu.credential.revoke.wizard'
    _description = 'Revoke Akahu Credentials'

    credential_id = fields.Many2one(
        'akahu.credential',
        string='Credential',
        required=True,
        readonly=True,
    )
    company_name = fields.Char(
        string='Company',
        compute='_compute_company_name',
    )
    linked_accounts_count = fields.Integer(
        string='Linked bank accounts',
        compute='_compute_linked_accounts_count',
    )
    confirm = fields.Boolean(
        string='I understand — clear all tokens for this company',
        default=False,
    )

    @api.depends('credential_id')
    def _compute_company_name(self):
        for rec in self:
            rec.company_name = rec.credential_id.company_id.name if rec.credential_id else ''

    @api.depends('credential_id')
    def _compute_linked_accounts_count(self):
        for rec in self:
            rec.linked_accounts_count = self.env['akahu.account'].search_count([
                ('credential_id', '=', rec.credential_id.id),
            ])

    def action_revoke(self):
        """
        Clear app_token, app_secret, and all linked user_tokens.

        Requires the admin to have ticked the confirmation checkbox.
        """
        # METHOD GUARD: Restricted to ERP Managers only (same group that can see the
        # credential fields). Prevents account managers from revoking credentials via RPC.
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Revoking credentials is restricted to ERP Managers.'))

        self.ensure_one()
        if not self.confirm:
            raise UserError(_(
                'Please tick the confirmation checkbox before revoking credentials.'
            ))

        cred = self.credential_id
        linked_accounts = self.env['akahu.account'].sudo().search([
            ('credential_id', '=', cred.id),
        ])

        remote_failures = []

        # Prefer authorisation-level revoke when authorisation IDs are available.
        auth_field_name = next((
            name for name in ('akahu_authorisation_id', 'authorisation_id')
            if name in linked_accounts._fields
        ), None)
        authorisation_rows = []
        if auth_field_name:
            for account in linked_accounts:
                authorisation_id = (account[auth_field_name] or '').strip()
                try:
                    user_token = account._get_user_token()
                except Exception as e:
                    remote_failures.append('authorisation-token-read (%s)' % str(e))
                    _logger.warning(
                        'Akahu remote revoke token read failed for credential_id=%s account_id=%s: %s',
                        cred.id,
                        account.id,
                        str(e),
                    )
                    continue
                if authorisation_id and user_token:
                    authorisation_rows.append((authorisation_id, user_token))

        if authorisation_rows:
            seen_authorisations = set()
            for authorisation_id, user_token in authorisation_rows:
                if authorisation_id in seen_authorisations:
                    continue
                seen_authorisations.add(authorisation_id)
                try:
                    cred._api_request(
                        user_token_plain=user_token,
                        path='/authorisations/%s' % authorisation_id,
                        method='DELETE',
                    )
                except Exception as e:
                    remote_failures.append('authorisation:%s (%s)' % (authorisation_id, str(e)))
                    _logger.warning(
                        'Akahu remote revoke failed for credential_id=%s authorisation_id=%s: %s',
                        cred.id,
                        authorisation_id,
                        str(e),
                    )
        else:
            # Fall back to token revoke once per unique user token.
            unique_tokens = set()
            for account in linked_accounts:
                try:
                    user_token = account._get_user_token()
                except Exception as e:
                    remote_failures.append('token-read (%s)' % str(e))
                    _logger.warning(
                        'Akahu remote token revoke read failed for credential_id=%s account_id=%s: %s',
                        cred.id,
                        account.id,
                        str(e),
                    )
                    continue
                if user_token:
                    unique_tokens.add(user_token)
            for user_token in unique_tokens:
                try:
                    cred._api_request(
                        user_token_plain=user_token,
                        path='/token',
                        method='DELETE',
                    )
                except Exception as e:
                    remote_failures.append('token (%s)' % str(e))
                    _logger.warning(
                        'Akahu remote token revoke failed for credential_id=%s: %s',
                        cred.id,
                        str(e),
                    )

        # VNZ-09 FIX: app_token / app_secret are required=True (NOT NULL).
        # Writing False sets NULL, which the DB constraint rejects — the
        # whole write rolled back and nothing was cleared, including the
        # linked user tokens below (never reached). Write empty strings
        # instead: they satisfy NOT NULL, _encrypt_token() treats a falsy
        # value as "nothing to encrypt" so no ciphertext is stored, and
        # _get_app_token()/_get_app_secret() will read back ''.
        #
        # sudo() needed here: revocation must succeed even if the current user
        # only has account.group_account_manager (not base.group_erp_manager),
        # because the field-level group restriction on app_token/app_secret
        # would otherwise block the write.
        cred.sudo().write({
            'app_token': '',
            'user_access_token': '',
            'app_secret': '',
            'connection_status': 'untested',
            'error_message': (
                'Credentials revoked by %s on %s. Re-enter tokens to resume sync.%s'
            ) % (
                self.env.user.name,
                fields.Datetime.now(),
                (
                    ' Remote Akahu revoke had %d failure(s); check server logs.'
                    % len(remote_failures)
                ) if remote_failures else '',
            ),
        })

        # Also wipe all linked user tokens so sync cannot resume with stale tokens.
        # VNZ-09 FIX: user_token is also required=True — same False->NULL
        # problem — write empty string here too.
        linked_accounts.write({'user_token': ''})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Credentials Revoked'),
                'message': _(
                    'All tokens for %s have been cleared. '
                    'Re-enter the App Token and User Access Token to resume sync.'
                ) % cred.company_id.name,
                'type': 'warning',
                'sticky': True,
            },
        }
