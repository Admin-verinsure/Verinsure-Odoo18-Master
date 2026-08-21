# -*- coding: utf-8 -*-
import uuid
from odoo import fields, models


class AkahuSyncRun(models.Model):
    _name = 'akahu.sync.run'
    _description = 'Akahu Sync Run Audit'
    _order = 'started_at desc, id desc'

    run_id = fields.Char(
        string='Run ID',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: str(uuid.uuid4()),
    )
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

    sync_mode = fields.Selection([
        ('first_sync', 'First Sync'),
        ('normal_incremental', 'Normal Incremental'),
        ('cursor_recovery', 'Cursor Recovery'),
        ('account_reconnected', 'Account Reconnected'),
        ('manual_recovery', 'Manual Recovery'),
    ], string='Sync Mode', default='normal_incremental', required=True)
    run_mode = fields.Selection([
        ('normal', 'Normal'),
        ('first_sync', 'First Sync'),
        ('recovery', 'Recovery'),
    ], string='Run Mode', default='normal', required=True)
    dry_run = fields.Boolean(string='Dry Run', default=False)

    cursor_before = fields.Char(string='Cursor Before', index=True)
    cursor_after = fields.Char(string='Cursor After', index=True)
    recovery_boundary_start = fields.Datetime(string='Recovery Boundary Start')
    recovery_start = fields.Datetime(string='Recovery Start')
    recovery_end = fields.Datetime(string='Recovery End')
    recovery_overlap_days = fields.Integer(string='Recovery Overlap Days', default=0)
    previous_checkpoint_date = fields.Datetime(string='Previous Checkpoint Date')
    previous_checkpoint_transaction_id = fields.Char(string='Previous Checkpoint Transaction ID', index=True)

    started_at = fields.Datetime(string='Started At', default=fields.Datetime.now, required=True, index=True)
    ended_at = fields.Datetime(string='Ended At', index=True)

    pages_fetched = fields.Integer(string='Pages Fetched', default=0)
    pages_requested = fields.Integer(string='Pages Requested', default=0)
    pages_processed = fields.Integer(string='Pages Processed', default=0)
    transactions_fetched = fields.Integer(string='Transactions Fetched', default=0)
    transactions_seen = fields.Integer(string='Transactions Seen', default=0)
    created_count = fields.Integer(string='Created Count', default=0)
    transactions_created = fields.Integer(string='Transactions Created', default=0)
    skipped_by_id_count = fields.Integer(string='Skipped by ID Count', default=0)
    transactions_imported = fields.Integer(string='Transactions Imported', default=0)
    transactions_skipped = fields.Integer(string='Transactions Skipped', default=0)
    transactions_duplicate = fields.Integer(string='Transactions Duplicate', default=0)
    transactions_skipped_same_id = fields.Integer(string='Skipped Same ID', default=0)
    transactions_skipped_lineage = fields.Integer(string='Skipped Lineage', default=0)
    transactions_skipped_fingerprint = fields.Integer(string='Skipped Fingerprint', default=0)
    possible_duplicates = fields.Integer(string='Possible Duplicates', default=0)
    identity_conflicts = fields.Integer(string='Identity Conflicts', default=0)
    matched_by_lineage_count = fields.Integer(string='Matched by Lineage Count', default=0)
    matched_by_fingerprint_count = fields.Integer(string='Matched by Fingerprint Count', default=0)
    ambiguous_count = fields.Integer(string='Ambiguous Count', default=0)
    recovery_limit_hit = fields.Boolean(string='Recovery Limit Hit', default=False)
    failure_reason = fields.Char(string='Failure Reason')
    identity_match_type = fields.Selection([
        ('exact_id', 'Exact ID'),
        ('lineage', 'Lineage'),
        ('fingerprint_high', 'Fingerprint (High Confidence)'),
        ('possible_fingerprint', 'Possible Fingerprint'),
        ('new', 'New'),
        ('identity_conflict', 'Identity Conflict'),
    ], string='Identity Match Type')

    anomaly_flags = fields.Text(string='Anomaly Flags')
    error_message = fields.Text(string='Error Message')
    status = fields.Selection([
        ('running', 'Running'),
        ('success', 'Success'),
        ('error', 'Error'),
        ('review_required', 'Review Required'),
        ('partial', 'Partial'),
    ], string='Status', default='running', required=True, index=True)

    _sql_constraints = [
        (
            'akahu_sync_run_run_id_uniq',
            'unique(run_id)',
            'Akahu sync run ID must be unique.',
        ),
    ]
