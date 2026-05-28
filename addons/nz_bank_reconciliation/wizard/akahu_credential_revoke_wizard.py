# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


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
        # METHOD GUARD: Restricted to ERP Managers only (same group that can see the
        # credential fields). Prevents account managers from revoking credentials via RPC.
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Revoking credentials is restricted to ERP Managers.'))

        Requires the admin to have ticked the confirmation checkbox.
        """
        self.ensure_one()
        if not self.confirm:
            raise UserError(_(
                'Please tick the confirmation checkbox before revoking credentials.'
            ))

        cred = self.credential_id
        # sudo() needed here: revocation must succeed even if the current user
        # only has account.group_account_manager (not base.group_erp_manager),
        # because the field-level group restriction on app_token/app_secret
        # would otherwise block the write.
        cred.sudo().write({
            'app_token': False,
            'app_secret': False,
            'connection_status': 'untested',
            'error_message': 'Credentials revoked by %s on %s. Re-enter tokens to resume sync.' % (
                self.env.user.name,
                fields.Datetime.now(),
            ),
        })

        # Also wipe all linked user tokens so sync cannot resume with stale tokens.
        linked_accounts = self.env['akahu.account'].sudo().search([
            ('credential_id', '=', cred.id),
        ])
        linked_accounts.write({'user_token': False})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Credentials Revoked'),
                'message': _(
                    'All tokens for %s have been cleared. '
                    'Re-enter the App Token, App Secret, and User Tokens to resume sync.'
                ) % cred.company_id.name,
                'type': 'warning',
                'sticky': True,
            },
        }
