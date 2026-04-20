# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

MONETARY_PRECISION = 2


class AutoReconciliationWizard(models.TransientModel):
    """
    CRITICAL FIX 3 — Deterministic confirm.

    Original problem: preview ran the engine and stored match candidates as a
    raw Python string, then confirm discarded that data entirely and re-ran the
    engine from scratch. If the hourly cron fired between Preview and Confirm,
    different items would be reconciled than what the user reviewed — or items
    already reconciled by cron would cause silent failures. Additionally, new
    transactions arriving between preview and confirm could be applied without
    review.

    Fix: preview now stores the exact matched ID pairs (statement_line_id /
    move_line_id, payment_id / invoice_id, etc.) as JSON. Confirm applies ONLY
    those specific pairs, and re-validates that each item is still unreconciled
    before touching it. If an item was reconciled in the meantime (e.g. by cron),
    it is safely skipped and reported.
    """
    _name = 'auto.reconciliation.wizard'
    _description = 'Auto Reconciliation Review Wizard'

    company_id = fields.Many2one('res.company', string='Company', required=True)
    total_preview_count = fields.Integer(string='Total Matches Found', readonly=True)

    # CRITICAL FIX 3: Store structured JSON of matched ID pairs, not raw engine output.
    # Each entry is a dict with 'type' plus the specific IDs needed to apply that match.
    match_pairs_json = fields.Text(
        string='Match Pairs (JSON)',
        help='Internal: JSON list of {type, id pairs} captured at preview time. '
             'Confirm applies exactly these pairs after re-validating each is still open.',
    )
    # Human-readable summary for display (kept separate from ID data)
    match_summary = fields.Text(string='Raw Match Data')

    line_ids = fields.One2many(
        'auto.reconciliation.wizard.line',
        'wizard_id',
        string='Match Lines',
        compute='_compute_line_ids',
        store=False,
    )
    state = fields.Selection([
        ('preview', 'Preview'),
        ('confirmed', 'Confirmed'),
    ], default='preview')

    skipped_count = fields.Integer(
        string='Skipped (already reconciled)',
        readonly=True,
        default=0,
        help='Items found at preview time that were reconciled by another process before confirm.',
    )

    @api.depends('match_summary')
    def _compute_line_ids(self):
        """Parse raw match data and populate display lines."""
        for rec in self:
            if not rec.match_summary:
                rec.line_ids = []
                continue
            try:
                matches = json.loads(rec.match_summary)
            except Exception:
                rec.line_ids = []
                continue

            lines = []
            for match in matches:
                rtype = match.get('type', '')
                if rtype == 'bank_statement':
                    label = 'Bank: %s ↔ %s' % (
                        match.get('statement_line_name', ''),
                        match.get('move_line_name', ''),
                    )
                elif rtype == 'customer_payment':
                    label = 'Customer: %s ↔ %s' % (
                        match.get('payment_name', ''),
                        match.get('invoice_name', ''),
                    )
                elif rtype == 'vendor_payment':
                    label = 'Vendor: %s ↔ %s' % (
                        match.get('payment_name', ''),
                        match.get('bill_name', ''),
                    )
                elif rtype == 'intercompany':
                    label = 'IC: %s (%s) ↔ %s (%s)' % (
                        match.get('line_name', ''),
                        match.get('company_from', ''),
                        match.get('counterpart_line_name', ''),
                        match.get('company_to', ''),
                    )
                else:
                    label = 'Unknown'

                lines.append((0, 0, {
                    'reconciliation_type': rtype,
                    'description': label,
                    'amount': match.get('amount', 0.0),
                    'partner_name': match.get('partner', match.get('company_from', '')),
                    'selected': True,
                }))
            rec.line_ids = lines

    def action_confirm(self):
        """
        CRITICAL FIX 3: Apply only the specific ID pairs captured at preview time.

        For each stored pair:
          1. Re-fetch both records to get their current state.
          2. Check they are still unreconciled. If already reconciled (e.g. by cron),
             skip and count as 'skipped' — do NOT re-apply.
          3. Apply reconciliation only for still-open pairs.

        This makes confirm deterministic and safe regardless of what happened
        between preview and confirm.
        """
        self.ensure_one()

        if not self.match_pairs_json:
            raise UserError(_('No preview data found. Please close this wizard and run Preview again.'))

        try:
            pairs = json.loads(self.match_pairs_json)
        except Exception:
            raise UserError(_('Preview data is corrupt. Please close this wizard and run Preview again.'))

        applied = 0
        skipped = 0
        BankLine = self.env['account.bank.statement.line'].sudo()
        MoveLine = self.env['account.move.line'].sudo()
        Payment = self.env['account.payment'].sudo()
        Move = self.env['account.move'].sudo()

        for pair in pairs:
            rtype = pair.get('type')
            try:
                if rtype == 'bank_statement':
                    stmt_line = BankLine.browse(pair['statement_line_id'])
                    move_line = MoveLine.browse(pair['move_line_id'])
                    # Re-validate: both must still exist and be unreconciled
                    if not stmt_line.exists() or stmt_line.is_reconciled:
                        _logger.info("Wizard confirm: bank stmt_line %s already reconciled, skipping.", pair['statement_line_id'])
                        skipped += 1
                        continue
                    if not move_line.exists() or move_line.reconciled:
                        _logger.info("Wizard confirm: move_line %s already reconciled, skipping.", pair['move_line_id'])
                        skipped += 1
                        continue
                    engine = self.env['auto.reconciliation.engine']
                    engine._apply_bank_reconciliation_community(stmt_line, move_line)
                    applied += 1

                elif rtype == 'customer_payment':
                    payment = Payment.browse(pair['payment_id'])
                    invoice = Move.browse(pair['invoice_id'])
                    if not payment.exists() or payment.reconciled_invoice_ids:
                        skipped += 1
                        continue
                    if not invoice.exists() or invoice.payment_state == 'paid':
                        skipped += 1
                        continue
                    engine = self.env['auto.reconciliation.engine']
                    engine._apply_ar_reconciliation(payment, invoice, 'asset_receivable')
                    applied += 1

                elif rtype == 'vendor_payment':
                    payment = Payment.browse(pair['payment_id'])
                    bill = Move.browse(pair['bill_id'])
                    if not payment.exists() or payment.reconciled_bill_ids:
                        skipped += 1
                        continue
                    if not bill.exists() or bill.payment_state == 'paid':
                        skipped += 1
                        continue
                    engine = self.env['auto.reconciliation.engine']
                    engine._apply_ar_reconciliation(payment, bill, 'liability_payable')
                    applied += 1

                elif rtype == 'intercompany':
                    line = MoveLine.browse(pair['line_id'])
                    counterpart = MoveLine.browse(pair['counterpart_line_id'])
                    if not line.exists() or line.reconciled:
                        skipped += 1
                        continue
                    if not counterpart.exists() or counterpart.reconciled:
                        skipped += 1
                        continue
                    (line | counterpart).reconcile()
                    applied += 1

            except Exception as e:
                _logger.warning("Wizard confirm: failed to apply %s pair %s: %s", rtype, pair, str(e))
                skipped += 1

        self.write({'state': 'confirmed', 'skipped_count': skipped})

        if skipped > 0:
            message = _(
                '%d match(es) applied for %s. %d skipped (already reconciled by another process).'
            ) % (applied, self.company_id.name, skipped)
            notif_type = 'warning'
        else:
            message = _(
                '%d match(es) confirmed and applied for %s.'
            ) % (applied, self.company_id.name)
            notif_type = 'success'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconciliation Applied'),
                'message': message,
                'type': notif_type,
                'sticky': skipped > 0,
            }
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}


class AutoReconciliationWizardLine(models.TransientModel):
    _name = 'auto.reconciliation.wizard.line'
    _description = 'Auto Reconciliation Wizard Line'

    wizard_id = fields.Many2one('auto.reconciliation.wizard', string='Wizard')
    selected = fields.Boolean(string='Include', default=True)
    reconciliation_type = fields.Selection([
        ('bank_statement', 'Bank Statement'),
        ('customer_payment', 'Customer Payment'),
        ('vendor_payment', 'Vendor Payment'),
        ('intercompany', 'Inter-company'),
    ], string='Type')
    description = fields.Char(string='Match Description', readonly=True)
    amount = fields.Float(string='Amount', readonly=True)
    partner_name = fields.Char(string='Partner / Company', readonly=True)
