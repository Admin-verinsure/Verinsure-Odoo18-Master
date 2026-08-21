# -*- coding: utf-8 -*-
from odoo import fields, models


class AkahuSyncState(models.Model):
    _name = 'akahu.sync.state'
    _description = 'Akahu Persistent Sync State'
    _order = 'write_date desc, id desc'

    journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        required=True,
        ondelete='restrict',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        index=True,
    )

    current_akahu_account_id = fields.Char(string='Current Akahu Account ID', index=True)
    previous_akahu_account_id = fields.Char(string='Previous Akahu Account ID', index=True)
    current_akahu_connection_id = fields.Char(string='Current Akahu Connection ID', index=True)
    previous_akahu_connection_id = fields.Char(string='Previous Akahu Connection ID', index=True)

    committed_cursor = fields.Char(string='Committed Cursor', index=True)
    inflight_cursor = fields.Char(string='In-Flight Cursor', index=True)
    inflight_page_no = fields.Integer(string='In-Flight Page Number', default=0)

    last_successful_transaction_id = fields.Char(string='Last Successful Transaction ID', index=True)
    last_successful_transaction_date = fields.Datetime(string='Last Successful Transaction Date')
    last_successful_fetch_at = fields.Datetime(string='Last Successful Fetch At')
    last_successful_sync_at = fields.Datetime(string='Last Successful Sync At')

    checkpoint_status = fields.Selection([
        ('ready', 'Ready'),
        ('inflight', 'In-Flight'),
        ('committed', 'Committed'),
        ('failed', 'Failed'),
    ], string='Checkpoint Status', default='ready', required=True)
    checkpoint_updated_at = fields.Datetime(string='Checkpoint Updated At')

    recovery_mode = fields.Selection([
        ('normal', 'Normal'),
        ('first_sync', 'First Sync'),
        ('recovery', 'Recovery'),
    ], string='Recovery Mode', default='first_sync', required=True)

    sync_mode = fields.Selection([
        ('first_sync', 'First Sync'),
        ('normal_incremental', 'Normal Incremental'),
        ('cursor_recovery', 'Cursor Recovery'),
        ('account_reconnected', 'Account Reconnected'),
        ('manual_recovery', 'Manual Recovery'),
    ], string='Sync Mode', default='first_sync', required=True)

    recovery_reason = fields.Char(string='Recovery Reason')
    recovery_window_start = fields.Datetime(string='Recovery Window Start')
    recovery_window_end = fields.Datetime(string='Recovery Window End')
    recovery_overlap_days = fields.Integer(string='Recovery Overlap (Days)', default=2)
    recovery_overlap_minutes = fields.Integer(string='Recovery Overlap (Minutes)', default=60)
    identity_match_window_days = fields.Integer(
        string='Identity Match Window (Days)',
        default=7,
        help='Maximum date distance allowed for high-confidence fingerprint matching.',
    )
    state_status = fields.Selection([
        ('ready', 'Ready'),
        ('running', 'Running'),
        ('review_required', 'Review Required'),
        ('failed', 'Failed'),
    ], string='State Status', default='ready', required=True)

    lock_owner_run_id = fields.Many2one(
        'akahu.sync.run',
        string='Lock Owner Run',
        ondelete='set null',
        index=True,
    )

    _sql_constraints = [
        (
            'akahu_sync_state_journal_uniq',
            'unique(journal_id)',
            'A persistent Akahu sync state already exists for this journal.',
        ),
    ]
