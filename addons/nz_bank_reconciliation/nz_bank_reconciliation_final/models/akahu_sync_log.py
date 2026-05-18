# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class AkahuSyncLog(models.Model):
    _name = 'akahu.sync.log'
    _description = 'Akahu Sync Log'
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference',
        compute='_compute_name',
        store=True,
    )
    akahu_account_id = fields.Many2one(
        'akahu.account',
        string='Akahu Account',
        ondelete='set null',
    )
    company_id = fields.Many2one('res.company', string='Company', required=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('partial', 'Partial'),
    ], string='Status', default='success')
    transactions_fetched = fields.Integer(string='Fetched from Akahu', default=0)
    transactions_imported = fields.Integer(string='Imported to Odoo', default=0)
    transactions_skipped = fields.Integer(
        string='Skipped (Duplicates)',
        compute='_compute_skipped',
        store=True,
    )
    error_message = fields.Text(string='Error Details')

    @api.depends('transactions_fetched', 'transactions_imported')
    def _compute_skipped(self):
        for rec in self:
            rec.transactions_skipped = max(
                0, rec.transactions_fetched - rec.transactions_imported
            )

    @api.depends('akahu_account_id', 'create_date')
    def _compute_name(self):
        for rec in self:
            # Guard: create_date is False on unsaved records. Without this,
            # strftime() raises AttributeError and store=True writes a broken
            # value before the post-save recompute can correct it.
            if not rec.create_date:
                rec.name = False
                continue
            acc = rec.akahu_account_id.name if rec.akahu_account_id else 'All'
            ts = rec.create_date.strftime('%Y%m%d-%H%M%S')
            rec.name = 'SYNC/%s/%s' % (acc, ts)
