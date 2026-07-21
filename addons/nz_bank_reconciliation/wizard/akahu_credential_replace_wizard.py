# -*- coding: utf-8 -*-
from odoo import models, fields, _


class AkahuCredentialReplaceWizard(models.TransientModel):
    _name = 'akahu.credential.replace.wizard'
    _description = 'Replace Akahu Credentials'

    credential_id = fields.Many2one(
        'akahu.credential',
        string='Credential',
        required=True,
        readonly=True,
    )
    new_app_token = fields.Char(
        string='New App Token',
        required=True,
    )
    new_app_secret = fields.Char(
        string='New App Secret',
        required=True,
    )

    def action_save(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Replacing credentials is restricted to ERP Managers.'))

        self.ensure_one()
        credential = self.credential_id.sudo()
        credential.write({
            'app_token': self.new_app_token,
            'app_secret': self.new_app_secret,
            'connection_status': 'untested',
            'error_message': False,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Credentials Updated'),
                'message': _('Akahu credentials were replaced successfully.'),
                'type': 'success',
            },
        }
