# -*- coding: utf-8 -*-
from odoo import models, fields, _


class AkahuAccountReplaceTokenWizard(models.TransientModel):
    _name = 'akahu.account.replace.token.wizard'
    _description = 'Replace Akahu User Token'

    account_id = fields.Many2one(
        'akahu.account',
        string='Bank Account',
        required=True,
        readonly=True,
    )
    new_user_token = fields.Char(
        string='New User Access Token',
        required=True,
    )

    def action_save(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Replacing user tokens is restricted to ERP Managers.'))

        self.ensure_one()
        account = self.account_id.sudo()
        account.write({
            'user_token': self.new_user_token,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('User Token Updated'),
                'message': _('The User Access Token has been replaced successfully.'),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
