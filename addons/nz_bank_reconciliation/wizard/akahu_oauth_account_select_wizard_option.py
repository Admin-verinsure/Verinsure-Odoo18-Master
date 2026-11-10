# -*- coding: utf-8 -*-
from odoo import fields, models


class AkahuOAuthAccountSelectWizardOption(models.TransientModel):
    _name = 'akahu.oauth.account.select.wizard.option'
    _description = 'Akahu OAuth Account Selection Option'
    _rec_name = 'display_name'

    wizard_id = fields.Many2one(
        'akahu.oauth.account.select.wizard',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Odoo Company',
        required=False,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Odoo Bank Journal',
        domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]",
    )
    selected = fields.Boolean(string='Map this account', default=False)
    akahu_account_id = fields.Char(required=True)
    display_name = fields.Char(required=True)
    bank_name = fields.Char(readonly=True)
    account_name = fields.Char(readonly=True)
    formatted_account = fields.Char(readonly=True)
    akahu_status = fields.Char(readonly=True)
