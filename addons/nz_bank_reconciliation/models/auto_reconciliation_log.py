# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


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
            # BUG FIX 4: create_date is False/None for unsaved records.
            # Previously this produced 'REC/<company>/' which got stored by
            # store=True before the post-save recompute could correct it.
            # Now we skip writing until both values are available, so the
            # stored name is always either a valid reference or blank (for
            # the brief window before first save — normal Odoo behaviour).
            if not rec.create_date:
                rec.name = False
                continue
            rec.name = 'REC/%s/%s' % (
                rec.company_id.name if rec.company_id else '',
                rec.create_date.strftime('%Y%m%d%H%M%S'),
            )

    def action_view_dashboard(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'auto_reconciliation_dashboard',
        }

    @api.model
    def get_dashboard_stats(self):
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

        """
        Return pre-aggregated stats via a single SQL SUM query instead of
        fetching every log record to the browser for client-side reduce().
        Without this, the JS dashboard loads thousands of records after a
        year of daily cron runs, causing browser hangs.

        BUG-02 FIX: `tuple(self.env.companies.ids)` is `()` on a fresh
        install or in test context, producing invalid SQL:
          WHERE company_id IN ()   -- PostgreSQL SyntaxError
        Fix: fall back to `(0,)` — a sentinel that matches no real company,
        so the query safely returns zero rows instead of crashing.

        Returns a dict with total_runs + per-type lifetime totals.
        """
        # BUG-02 FIX: Guard against empty tuple → invalid SQL.
        company_ids = tuple(self.env.companies.ids) or (0,)
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
        """, (company_ids,))
        row = self.env.cr.dictfetchone()
        return {
            'total_runs':            int(row['total_runs']),
            'total_matched':         int(row['total_matched']),
            'bank_matched':          int(row['bank_matched']),
            'customer_matched':      int(row['customer_matched']),
            'vendor_matched':        int(row['vendor_matched']),
            'intercompany_matched':  int(row['intercompany_matched']),
        }

    # ── Log retention (clause 2.4.1.e) ────────────────────────────────────────

    @api.model
    def cron_purge_old_logs(self, days=90):
        """
        LOG RETENTION FIX (clause 2.4.1.e): Delete reconciliation log entries
        older than *days* days (default 90).  Called by the scheduled purge cron.

        sudo() needed so the cron technical user (which has no unlink permission
        on auto.reconciliation.log) can perform the delete.  Scope is strictly
        limited to records older than the cutoff.
        """
        # METHOD GUARD: Raises AccessError if the RPC caller is not an Accounting Manager.
        # This prevents unprivileged internal users from invoking this method directly
        # via XML-RPC or JSON-RPC, which bypasses the UI but not the ORM method layer.
        if not self.env.user.has_group('account.group_account_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('This action is restricted to Accounting Managers.'))

        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        old = self.sudo().search([('create_date', '<', cutoff)])
        count = len(old)
        old.unlink()
        _logger.info(
            'Auto reconciliation log purge: deleted %d entries older than %d days.',
            count, days,
        )
