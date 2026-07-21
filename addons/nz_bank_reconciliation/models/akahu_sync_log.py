# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from ..utils.log_redaction import sanitize_log_value

_logger = logging.getLogger(__name__)


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

    # ── Log retention (clause 2.4.1.e) ────────────────────────────────────────

    @api.model
    def cron_purge_old_logs(self, days=90):
        """
        LOG RETENTION FIX (clause 2.4.1.e): Delete sync log entries older
        than *days* days (default 90).  Called by the scheduled purge cron.

        VNZ-02 FIX: this is destructive and previously ran unscoped under
        sudo() with a caller-controlled ``days`` value, letting any
        Accounting Manager erase every company's audit trail in one call.
        Now: (1) restricted to ERP Manager, a stricter group than the normal
        operator role; (2) ``days`` is validated so it cannot be used to
        bypass the retention window; (3) the delete is scoped to the
        caller's own companies even though sudo() is used to get past the
        unlink ACL gap for the cron technical user.
        """
        # METHOD GUARD (VNZ-02): raised to ERP Manager — a normal Accounting
        # Manager can no longer invoke this destructive method via RPC.
        if not self.env.user.has_group('base.group_erp_manager'):
            from odoo.exceptions import AccessError
            raise AccessError(_('Purging sync logs is restricted to ERP Managers.'))

        if not isinstance(days, int) or days < 1:
            from odoo.exceptions import UserError
            raise UserError(_('Retention window must be a positive number of days.'))

        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        # VNZ-02 FIX: scope to the caller's own companies instead of every
        # company in the database.
        company_ids = self.env.companies.ids
        old = self.sudo().search([
            ('create_date', '<', cutoff),
            ('company_id', 'in', company_ids),
        ])
        count = len(old)
        old.unlink()
        _logger.info(
            'Akahu sync log purge: deleted %d entries older than %d days for companies %s.',
            sanitize_log_value(count),
            sanitize_log_value(days),
            sanitize_log_value(company_ids),
        )
