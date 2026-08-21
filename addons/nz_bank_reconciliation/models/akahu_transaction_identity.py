# -*- coding: utf-8 -*-
from odoo import fields, models


class AkahuTransactionIdentity(models.Model):
    _name = 'akahu.transaction.identity'
    _description = 'Akahu Transaction Identity Registry'
    _order = 'last_seen_at desc, id desc'

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

    akahu_transaction_id = fields.Char(string='Akahu Transaction ID', index=True)
    akahu_account_id = fields.Char(string='Akahu Account ID', index=True)
    akahu_connection_id = fields.Char(string='Akahu Connection ID', index=True)
    akahu_migrated_from = fields.Char(string='Akahu Migrated From', index=True)
    akahu_migrated_account = fields.Char(string='Akahu Migrated Account', index=True)
    first_seen_akahu_account_id = fields.Char(string='First Seen Akahu Account ID', index=True)
    last_seen_akahu_account_id = fields.Char(string='Last Seen Akahu Account ID', index=True)
    first_seen_akahu_connection_id = fields.Char(string='First Seen Akahu Connection ID', index=True)
    last_seen_akahu_connection_id = fields.Char(string='Last Seen Akahu Connection ID', index=True)

    transaction_fingerprint = fields.Char(string='Transaction Fingerprint', index=True)
    relation_type = fields.Selection([
        ('exact_id', 'Exact ID'),
        ('migrated_from', 'Migrated From'),
        ('migrated_account', 'Migrated Account'),
        ('fingerprint_high', 'Fingerprint High Confidence'),
        ('possible_fingerprint', 'Possible Fingerprint'),
        ('new', 'New'),
        ('identity_conflict', 'Identity Conflict'),
    ], string='Relation Type', default='new', required=True, index=True)
    confidence = fields.Selection([
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('unknown', 'Unknown'),
    ], string='Confidence', default='unknown', required=True, index=True)
    identity_match_type = fields.Selection([
        ('exact_id', 'Exact ID'),
        ('lineage', 'Lineage'),
        ('fingerprint_high', 'Fingerprint (High Confidence)'),
        ('possible_fingerprint', 'Possible Fingerprint'),
        ('new', 'New'),
        ('identity_conflict', 'Identity Conflict'),
    ], string='Identity Match Type', default='new', required=True, index=True)
    is_replacement_current = fields.Boolean(string='Is Replacement Current', default=True, index=True)
    supersedes_identity_id = fields.Many2one(
        'akahu.transaction.identity',
        string='Supersedes Identity',
        ondelete='set null',
        index=True,
    )
    matched_fields = fields.Text(string='Matched Fields')
    conflicting_fields = fields.Text(string='Conflicting Fields')
    source_payload_signature = fields.Char(string='Source Payload Signature', index=True)
    forensic_note = fields.Text(string='Forensic Note')

    statement_line_id = fields.Many2one(
        'account.bank.statement.line',
        string='Statement Line',
        ondelete='set null',
        index=True,
    )
    first_seen_run_id = fields.Many2one(
        'akahu.sync.run',
        string='First Seen Run',
        ondelete='set null',
        index=True,
    )
    last_seen_run_id = fields.Many2one(
        'akahu.sync.run',
        string='Last Seen Run',
        ondelete='set null',
        index=True,
    )
    first_seen_at = fields.Datetime(string='First Seen At', default=fields.Datetime.now, required=True)
    last_seen_at = fields.Datetime(string='Last Seen At', default=fields.Datetime.now, required=True, index=True)

    _sql_constraints = [
        (
            'akahu_tx_identity_journal_txid_uniq',
            'unique(journal_id, akahu_transaction_id)',
            'Akahu transaction identity already exists for this journal.',
        ),
    ]
