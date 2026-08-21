# -*- coding: utf-8 -*-
from odoo import models, fields, _
from odoo.exceptions import UserError, AccessError


class AkahuAccountSelectWizard(models.TransientModel):
    _name = 'akahu.account.select.wizard'
    _description = 'Select Akahu Account'

    account_id = fields.Many2one(
        'akahu.account',
        string='Akahu Account Record',
        required=True,
        readonly=True,
    )
    available_account_id = fields.Selection(
        selection='_selection_available_accounts',
        string='Available Akahu Account',
        required=True,
    )

    def _selection_available_accounts(self):
        options = []
        available = self.env.context.get('akahu_available_accounts') or []
        for item in available:
            akahu_id = item.get('id') or ''
            label = '%s | %s | %s' % (
                item.get('bank_name') or _('Unknown Bank'),
                item.get('account_number') or _('No Account Number'),
                item.get('account_name') or akahu_id,
            )
            options.append((akahu_id, label))
        return options

    def action_confirm(self):
        if not self.env.user.has_group('base.group_erp_manager'):
            raise AccessError(_('This action is restricted to ERP Managers.'))

        self.ensure_one()
        available = self.env.context.get('akahu_available_accounts') or []
        selected = next(
            (item for item in available if item.get('id') == self.available_account_id),
            None,
        )
        if not selected:
            raise UserError(_('Please select a valid Akahu account.'))

        vals = {
            'akahu_account_id': selected.get('id'),
            'bank_name': selected.get('bank_name'),
            'akahu_formatted_account': selected.get('account_number'),
            'akahu_account_name': selected.get('account_name'),
            'akahu_status': selected.get('status') or 'UNKNOWN',
            'balance_available': selected.get('balance_available') or 0.0,
        }
        refreshed_ts = selected.get('refreshed')
        if refreshed_ts:
            vals['last_refreshed'] = fields.Datetime.from_string(
                refreshed_ts.replace('T', ' ').split('.')[0]
            )

        self.account_id.write(vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Akahu Account Linked'),
                'message': _(
                    'Selected Akahu account has been linked and account info populated.'
                ),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
