# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class AkahuDuplicateFindingBatch(models.Model):
    _name = 'akahu.duplicate.finding.batch'
    _description = 'Akahu Duplicate Finding Batch'
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Batch Reference', required=True, copy=False, default='AKAHU-DUP-BATCH')
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Bank Journal',
        required=True,
        ondelete='restrict',
        index=True,
    )
    sync_run_id = fields.Many2one(
        'akahu.sync.run',
        string='Sync Run',
        ondelete='set null',
        index=True,
    )
    finding_count = fields.Integer(string='Finding Count', default=0, readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('completed', 'Completed'),
    ], string='State', default='draft', required=True, readonly=True, index=True)
    note = fields.Text(string='Note', readonly=True)

    finding_ids = fields.One2many(
        'akahu.duplicate.finding',
        'batch_id',
        string='Findings',
        readonly=True,
    )

    def write(self, vals):
        if not self.env.context.get('allow_akahu_forensic_write'):
            raise UserError(_('Akahu duplicate finding batches are immutable forensic records.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('allow_akahu_forensic_unlink'):
            raise UserError(_('Akahu duplicate finding batches cannot be deleted.'))
        return super().unlink()


class AkahuDuplicateFinding(models.Model):
    _name = 'akahu.duplicate.finding'
    _description = 'Akahu Duplicate Finding'
    _order = 'id desc'

    batch_id = fields.Many2one(
        'akahu.duplicate.finding.batch',
        string='Batch',
        required=True,
        ondelete='cascade',
        index=True,
        readonly=True,
    )
    company_id = fields.Many2one('res.company', string='Company', required=True, index=True, readonly=True)
    journal_id = fields.Many2one('account.journal', string='Bank Journal', required=True, ondelete='restrict', index=True, readonly=True)

    classification = fields.Selection([
        ('high_confidence_duplicate', 'High Confidence Duplicate'),
        ('possible_duplicate', 'Possible Duplicate'),
        ('legitimate_distinct_transaction', 'Legitimate Distinct Transaction'),
        ('unknown', 'Unknown'),
    ], string='Classification', default='unknown', required=True, readonly=True, index=True)
    confidence = fields.Selection([
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
        ('unknown', 'Unknown'),
    ], string='Confidence', default='unknown', required=True, readonly=True, index=True)
    identity_match_type = fields.Selection([
        ('exact_id', 'Exact ID'),
        ('lineage', 'Lineage'),
        ('fingerprint_high', 'Fingerprint (High Confidence)'),
        ('possible_fingerprint', 'Possible Fingerprint'),
        ('new', 'New'),
        ('identity_conflict', 'Identity Conflict'),
    ], string='Identity Match Type', default='new', required=True, readonly=True, index=True)

    existing_statement_line_id = fields.Many2one(
        'account.bank.statement.line',
        string='Existing Statement Line',
        ondelete='set null',
        index=True,
        readonly=True,
    )
    incoming_statement_line_id = fields.Many2one(
        'account.bank.statement.line',
        string='Incoming Statement Line',
        ondelete='set null',
        index=True,
        readonly=True,
    )

    existing_unique_import_id = fields.Char(string='Existing Unique Import ID', readonly=True, index=True)
    incoming_unique_import_id = fields.Char(string='Incoming Unique Import ID', readonly=True, index=True)

    existing_akahu_transaction_id = fields.Char(string='Existing Akahu Transaction ID', readonly=True, index=True)
    incoming_akahu_transaction_id = fields.Char(string='Incoming Akahu Transaction ID', readonly=True, index=True)
    incoming_akahu_migrated_from = fields.Char(string='Incoming Akahu Migrated From', readonly=True, index=True)
    incoming_akahu_migrated_account = fields.Char(string='Incoming Akahu Migrated Account', readonly=True, index=True)

    existing_date = fields.Date(string='Existing Date', readonly=True, index=True)
    incoming_date = fields.Date(string='Incoming Date', readonly=True, index=True)
    existing_amount = fields.Float(string='Existing Amount', readonly=True)
    incoming_amount = fields.Float(string='Incoming Amount', readonly=True)
    existing_payment_ref = fields.Char(string='Existing Payment Ref', readonly=True)
    incoming_payment_ref = fields.Char(string='Incoming Payment Ref', readonly=True)
    existing_partner_name = fields.Char(string='Existing Partner', readonly=True)
    incoming_partner_name = fields.Char(string='Incoming Partner', readonly=True)

    existing_fingerprint = fields.Char(string='Existing Fingerprint', readonly=True, index=True)
    incoming_fingerprint = fields.Char(string='Incoming Fingerprint', readonly=True, index=True)

    matching_fields = fields.Text(string='Matching Fields', readonly=True)
    conflicting_fields = fields.Text(string='Conflicting Fields', readonly=True)
    reason = fields.Text(string='Reason', readonly=True)

    existing_is_reconciled = fields.Boolean(string='Existing Line Reconciled', readonly=True)
    existing_move_id = fields.Many2one(
        'account.move',
        string='Existing Linked Move',
        ondelete='set null',
        index=True,
        readonly=True,
    )
    existing_move_name = fields.Char(string='Existing Move Name', readonly=True)

    def write(self, vals):
        if not self.env.context.get('allow_akahu_forensic_write'):
            raise UserError(_('Akahu duplicate findings are immutable forensic records.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('allow_akahu_forensic_unlink'):
            raise UserError(_('Akahu duplicate findings cannot be deleted.'))
        return super().unlink()
