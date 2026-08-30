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
    journal_id = fields.Many2one(
        'account.journal',
        string='Odoo Bank Journal',
        required=False,
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
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
        required=False,
        domain="[('wizard_id', '=', id)]",
    )

    def action_save(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('Connecting Akahu is restricted to ERP Managers.'))

        self.ensure_one()
        if not self.journal_id:
            raise UserError(_('Please select an Odoo bank journal.'))
        if not self.selected_option_id:
            raise UserError(_('Please select an Akahu bank account.'))
        if self.selected_option_id.wizard_id != self:
            raise ValidationError(_('The selected Akahu account option does not belong to this OAuth session.'))

        if self.journal_id.company_id.id != self.credential_id.company_id.id:
            raise ValidationError(_('The selected journal must belong to the same company as the credential.'))

        account_model = self.env['akahu.account'].sudo()
        foreign_for_journal = account_model.search([
            ('company_id', '=', self.credential_id.company_id.id),
            ('journal_id', '=', self.journal_id.id),
            ('credential_id', '!=', self.credential_id.id),
        ], limit=1)
        if foreign_for_journal:
            raise ValidationError(_('This Odoo journal is already linked to another Akahu credential configuration.'))

        existing_for_journal = account_model.search([
            ('company_id', '=', self.credential_id.company_id.id),
            ('journal_id', '=', self.journal_id.id),
            ('credential_id', '=', self.credential_id.id),
        ], limit=1)
        existing_for_akahu = account_model.search([
            ('company_id', '=', self.credential_id.company_id.id),
            ('akahu_account_id', '=', self.selected_option_id.akahu_account_id),
            ('credential_id', '=', self.credential_id.id),
        ], limit=1)

        if existing_for_akahu and existing_for_journal and existing_for_akahu != existing_for_journal:
            raise ValidationError(_('This Akahu account is already linked to another Odoo bank configuration.'))
        if existing_for_akahu and existing_for_akahu.journal_id and existing_for_akahu.journal_id != self.journal_id:
            raise ValidationError(_('This Akahu account is already linked to another Odoo journal.'))

        target_account = existing_for_journal or existing_for_akahu
        vals = {
            'company_id': self.credential_id.company_id.id,
            'credential_id': self.credential_id.id,
            'journal_id': self.journal_id.id,
            'akahu_account_id': self.selected_option_id.akahu_account_id,
            'bank_name': self.selected_option_id.bank_name,
            'akahu_account_name': self.selected_option_id.account_name,
            'akahu_formatted_account': self.selected_option_id.formatted_account,
            'akahu_status': self.selected_option_id.akahu_status or 'UNKNOWN',
        }
        if target_account:
            target_account.write(vals)
        else:
            target_account = account_model.create(vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Akahu Connected'),
                'message': _('The selected Akahu bank account has been saved.'),
                'type': 'success',
                'next': {
                    'type': 'ir.actions.act_window',
                    'res_model': 'akahu.account',
                    'res_id': target_account.id,
                    'view_mode': 'form',
                    'target': 'current',
                },
            },
        }
