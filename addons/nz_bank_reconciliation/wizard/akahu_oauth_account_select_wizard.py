# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


class AkahuOAuthAccountSelectWizard(models.TransientModel):
    _name = 'akahu.oauth.account.select.wizard'
    _description = 'Akahu OAuth Account Selection'

    credential_id = fields.Many2one(
        'akahu.credential',
        string='Credential',
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        related='credential_id.company_id',
        readonly=True,
    )
    account_id = fields.Many2one(
        'akahu.account',
        string='Odoo Bank Account Configuration',
        required=True,
        domain="[('company_id', '=', company_id), ('credential_id', '=', credential_id)]",
    )
    option_ids = fields.One2many(
        'akahu.oauth.account.select.wizard.option',
        'wizard_id',
        string='Available Akahu Bank Accounts',
        readonly=True,
    )
    selected_option_id = fields.Many2one(
        'akahu.oauth.account.select.wizard.option',
        string='Akahu Bank Account',
        required=True,
        domain="[('wizard_id', '=', id)]",
    )

    def action_save(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('Connecting Akahu is restricted to ERP Managers.'))

        self.ensure_one()
        if not self.selected_option_id:
            raise UserError(_('Please select an Akahu bank account.'))
        if self.selected_option_id.wizard_id != self:
            raise ValidationError(_('The selected Akahu account option does not belong to this OAuth session.'))

        account = self.account_id.sudo()
        if account.company_id.id != self.credential_id.company_id.id:
            raise ValidationError(_('The selected account must belong to the same company as the credential.'))
        if account.credential_id.id != self.credential_id.id:
            raise ValidationError(_('The selected account must use the same Akahu credential.'))

        account.write({
            'akahu_account_id': self.selected_option_id.akahu_account_id,
            'bank_name': self.selected_option_id.bank_name,
            'akahu_account_name': self.selected_option_id.account_name,
            'akahu_formatted_account': self.selected_option_id.formatted_account,
            'akahu_status': self.selected_option_id.akahu_status or 'UNKNOWN',
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Akahu Connected'),
                'message': _('The selected Akahu bank account has been saved.'),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
