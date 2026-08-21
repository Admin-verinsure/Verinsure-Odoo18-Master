# -*- coding: utf-8 -*-
from odoo import models, fields


class AccountBankStatementLine(models.Model):
    """
    VNZ-05 FIX: the sync engine deduplicates and inserts Akahu transactions
    using a `unique_import_id` field on account.bank.statement.line. That
    field belonged to Odoo's older bank-statement-import framework and does
    NOT exist on a stock Odoo 18 Community install (no `account_bank_statement_import`
    module declared as a dependency) — every dedup query and every insert
    failed with the target platform.

    This module now supplies the column itself so both the raw SQL dedup
    query in akahu_sync_engine.py and the ORM create() in
    _map_transaction_to_statement_line() have a real field to read/write,
    on every Odoo 18 edition (Community or Enterprise) regardless of which
    other modules are installed.
    """
    _inherit = 'account.bank.statement.line'

    unique_import_id = fields.Char(
        string='Import ID',
        copy=False,
        index=True,
        help='Set by bank-feed integrations (including Akahu sync) to '
             'deduplicate imported transactions. Not user-editable.',
    )
    akahu_transaction_id = fields.Char(
        string='Akahu Transaction ID',
        copy=False,
        index=True,
    )
    akahu_account_id = fields.Char(
        string='Akahu Account ID',
        copy=False,
        index=True,
    )
    akahu_connection_id = fields.Char(
        string='Akahu Connection ID',
        copy=False,
        index=True,
    )
    akahu_migrated_from = fields.Char(
        string='Akahu Migrated From',
        copy=False,
        index=True,
    )
    akahu_migrated_account = fields.Char(
        string='Akahu Migrated Account',
        copy=False,
        index=True,
    )
    akahu_transaction_fingerprint = fields.Char(
        string='Akahu Transaction Fingerprint',
        copy=False,
        index=True,
    )
    akahu_identity_confidence = fields.Selection([
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('unknown', 'Unknown'),
    ], string='Akahu Identity Confidence', default='unknown', copy=False, index=True)
    akahu_identity_match_type = fields.Selection([
        ('exact_id', 'Exact ID'),
        ('lineage', 'Lineage'),
        ('fingerprint_high', 'Fingerprint (High Confidence)'),
        ('possible_fingerprint', 'Possible Fingerprint'),
        ('new', 'New'),
        ('identity_conflict', 'Identity Conflict'),
    ], string='Akahu Identity Match Type', default='new', copy=False, index=True)
    akahu_identity_last_seen_at = fields.Datetime(
        string='Akahu Identity Last Seen At',
        copy=False,
        index=True,
    )
    akahu_identity_note = fields.Text(
        string='Akahu Identity Note',
        copy=False,
    )
    akahu_sync_run_id = fields.Many2one(
        'akahu.sync.run',
        string='Akahu Sync Run',
        copy=False,
        index=True,
        ondelete='set null',
    )

    _sql_constraints = [
        (
            'unique_import_id_uniq',
            'unique(unique_import_id, journal_id)',
            'A transaction with this Import ID has already been imported into this journal.',
        ),
    ]
