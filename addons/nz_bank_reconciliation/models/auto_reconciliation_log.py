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

    @api.model
    def get_dashboard_stats(self):
        """
        BUG FIX: Return pre-aggregated stats via a single SQL SUM query instead
        of fetching every log record to the browser for client-side reduce().
        Without this fix, the JS dashboard would load thousands of records after
        a year of daily cron runs, causing browser hangs.

        Returns a dict with total_runs + per-type lifetime totals.
        """
        self.env.cr.execute("""
            SELECT
                COUNT(*)                    AS total_runs,
                COALESCE(SUM(total_matched), 0)         AS total_matched,
                COALESCE(SUM(bank_matched), 0)          AS bank_matched,
                COALESCE(SUM(customer_matched), 0)      AS customer_matched,
                COALESCE(SUM(vendor_matched), 0)        AS vendor_matched,
                COALESCE(SUM(intercompany_matched), 0)  AS intercompany_matched
            FROM auto_reconciliation_log
            WHERE state = 'done'
              AND company_id IN %s
        """, (tuple(self.env.companies.ids),))
        row = self.env.cr.dictfetchone()
        return {
            'total_runs':            int(row['total_runs']),
            'total_matched':         int(row['total_matched']),
            'bank_matched':          int(row['bank_matched']),
            'customer_matched':      int(row['customer_matched']),
            'vendor_matched':        int(row['vendor_matched']),
            'intercompany_matched':  int(row['intercompany_matched']),
        }
