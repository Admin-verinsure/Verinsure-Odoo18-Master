# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class AutoReconciliationLog(models.Model):
    _name = 'auto.reconciliation.log'
    _description = 'Auto Reconciliation Log'
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference',
        compute='_compute_name',
        store=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    triggered_by = fields.Selection([
        ('manual', 'Manual'),
        ('cron', 'Scheduled'),
    ], string='Triggered By', default='manual')

    # Match counts per type
    bank_matched = fields.Integer(string='Bank Matches', default=0)
    customer_matched = fields.Integer(string='Customer Payment Matches', default=0)
    vendor_matched = fields.Integer(string='Vendor Payment Matches', default=0)
    intercompany_matched = fields.Integer(string='Inter-company Matches', default=0)
    total_matched = fields.Integer(string='Total Matches', default=0)

    state = fields.Selection([
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ], string='Status', default='running')

    notes = fields.Text(string='Notes')

    @api.depends('company_id', 'create_date')
    def _compute_name(self):
        for rec in self:
            rec.name = 'REC/%s/%s' % (
                rec.company_id.name if rec.company_id else '',
                rec.create_date.strftime('%Y%m%d%H%M%S') if rec.create_date else '',
            )

    def action_view_dashboard(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'auto_reconciliation_dashboard',
        }
