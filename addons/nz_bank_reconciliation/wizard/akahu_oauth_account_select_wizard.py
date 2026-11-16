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
    )
    selected_option_id = fields.Many2one(
        'akahu.oauth.account.select.wizard.option',
        string='Akahu Bank Account',
        required=False,
        domain="[('wizard_id', '=', id)]",
    )

    def _get_selected_options(self):
        self.ensure_one()
        selected = self.option_ids.filtered(lambda rec: rec.selected)
        if selected:
            return selected
        if self.selected_option_id:
            return self.option_ids.filtered(lambda rec: rec.id == self.selected_option_id.id)
        return self.option_ids.browse()

    def action_save(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('Connecting Akahu is restricted to ERP Managers.'))

        self.ensure_one()
        if self.selected_option_id and self.selected_option_id.wizard_id != self:
            raise ValidationError(_('The selected Akahu account option does not belong to this OAuth session.'))

        selected_options = self._get_selected_options()
        if self.selected_option_id and self.journal_id and selected_options and len(selected_options) == 1:
            selected_options.write({
                'selected': True,
                'company_id': self.company_id.id or self.credential_id.company_id.id,
                'journal_id': self.journal_id.id,
            })
        if not selected_options:
            raise UserError(_('Please select at least one Akahu bank account.'))

        account_model = self.env['akahu.account'].sudo()
        seen_akahu_ids = set()
        seen_journal_keys = set()
        valid_rows = []

        with self.env.cr.savepoint():
            for option in selected_options:
                if not option.company_id:
                    raise UserError(_('Please select an Odoo company for %s.') % option.display_name)
                if not option.journal_id:
                    raise UserError(_('Please select an Odoo bank journal for %s.') % option.display_name)
                if option.company_id.id != self.credential_id.company_id.id:
                    raise ValidationError(_('The selected Odoo company for %s must match the credential company.') % option.display_name)
                if option.journal_id.type != 'bank':
                    raise ValidationError(_('The selected journal for %s must be a Bank journal.') % option.display_name)
                if option.journal_id.company_id.id != option.company_id.id:
                    raise ValidationError(_('The selected journal for %s must belong to the selected Odoo company.') % option.display_name)

                akahu_key = option.akahu_account_id
                if akahu_key in seen_akahu_ids:
                    raise ValidationError(_('The same Akahu account has been selected more than once in this session.'))
                seen_akahu_ids.add(akahu_key)

                journal_key = (option.company_id.id, option.journal_id.id)
                if journal_key in seen_journal_keys:
                    raise ValidationError(_('The same Odoo bank journal has been selected more than once in this session.'))
                seen_journal_keys.add(journal_key)

                foreign_for_journal = account_model.search([
                    ('company_id', '=', option.company_id.id),
                    ('journal_id', '=', option.journal_id.id),
                    ('credential_id', '!=', self.credential_id.id),
                ], limit=1)
                if foreign_for_journal:
                    raise ValidationError(_('This Odoo journal is already linked to another Akahu credential configuration.'))

                existing_for_akahu = account_model.search([
                    ('company_id', '=', option.company_id.id),
                    ('akahu_account_id', '=', option.akahu_account_id),
                ], limit=1)
                if existing_for_akahu and existing_for_akahu.credential_id.id != self.credential_id.id:
                    raise ValidationError(_('This Akahu account is already linked to another credential configuration.'))
                if existing_for_akahu and existing_for_akahu.journal_id and existing_for_akahu.journal_id.id != option.journal_id.id:
                    raise ValidationError(_('This Akahu account is already linked to another Odoo journal.'))

                existing_for_journal = account_model.search([
                    ('company_id', '=', option.company_id.id),
                    ('journal_id', '=', option.journal_id.id),
                    ('credential_id', '=', self.credential_id.id),
                ], limit=1)
                if existing_for_journal and existing_for_journal.akahu_account_id and existing_for_journal.akahu_account_id != option.akahu_account_id:
                    raise ValidationError(_('This Odoo journal is already linked to a different Akahu account.'))

                valid_rows.append((option, existing_for_journal or existing_for_akahu))

            created_or_updated = []
            for option, target_account in valid_rows:
                vals = {
                    'company_id': option.company_id.id,
                    'credential_id': self.credential_id.id,
                    'journal_id': option.journal_id.id,
                    'akahu_account_id': option.akahu_account_id,
                    'bank_name': option.bank_name,
                    'akahu_account_name': option.account_name,
                    'akahu_formatted_account': option.formatted_account,
                    'akahu_status': option.akahu_status or 'UNKNOWN',
                }
                if target_account:
                    target_account.write(vals)
                else:
                    target_account = account_model.create(vals)
                created_or_updated.append(target_account)

        if not created_or_updated:
            raise UserError(_('No valid Akahu account mappings were selected.'))

        if len(created_or_updated) == 1:
            target_account = created_or_updated[0]
            message = _('The selected Akahu bank account has been saved.')
        else:
            target_account = created_or_updated[0]
            message = _('%d Akahu bank accounts have been saved.') % len(created_or_updated)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Akahu Connected'),
                'message': message,
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
