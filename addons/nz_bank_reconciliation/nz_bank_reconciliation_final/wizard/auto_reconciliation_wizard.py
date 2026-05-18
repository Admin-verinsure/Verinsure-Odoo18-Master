# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AutoReconciliationWizard(models.TransientModel):
    _name = 'auto.reconciliation.wizard'
    _description = 'Auto Reconciliation Review Wizard'

    company_id = fields.Many2one('res.company', string='Company', required=True)
    total_preview_count = fields.Integer(string='Total Matches Found', readonly=True)
    # match_summary kept for reference/display only — actual apply logic uses match_pairs_json
    match_summary = fields.Text(string='Raw Match Data')
    # Stores exact ID pairs captured at preview time.
    # confirm() applies only these — engine never re-runs from scratch.
    match_pairs_json = fields.Text(string='Match Pairs JSON')

    # CRITICAL FIX: line_ids must NOT be a computed field.
    # A computed One2many with no inverse= raises "Field is not stored and cannot
    # be inversed" the moment the user unchecks a row — making the entire
    # preview/select/confirm workflow non-functional.
    # Fix: plain writable One2many. Lines are created explicitly in
    # action_open_wizard() by the config model after the wizard record is saved.
    line_ids = fields.One2many(
        'auto.reconciliation.wizard.line', 'wizard_id',
        string='Match Lines',
    )

    state = fields.Selection([
        ('preview', 'Preview'), ('confirmed', 'Confirmed'),
    ], default='preview')
    skipped_count = fields.Integer(string='Skipped', readonly=True, default=0)
    selected_count = fields.Integer(
        string='Selected',
        compute='_compute_selected_count',
    )

    @api.depends('line_ids', 'line_ids.selected')
    def _compute_selected_count(self):
        for rec in self:
            rec.selected_count = sum(1 for l in rec.line_ids if l.selected)

    def action_confirm(self):
        """
        Apply only the specific ID pairs from preview time that the user
        has left selected (selected=True).  Each record is re-validated as
        still unreconciled before applying — items reconciled in the
        meantime (e.g. by cron) are safely skipped.
        """
        self.ensure_one()
        if not self.match_pairs_json:
            raise UserError(_('No preview data found. Please close and run Preview again.'))
        try:
            all_pairs = json.loads(self.match_pairs_json)
        except Exception:
            raise UserError(_('Preview data is corrupt. Please close and run Preview again.'))

        # Only process pairs whose wizard line is still selected.
        selected_indices = {
            line.pair_index for line in self.line_ids if line.selected
        }
        pairs = [
            p for i, p in enumerate(all_pairs)
            if i in selected_indices
        ]

        if not pairs:
            raise UserError(_('No matches selected. Please select at least one match to apply.'))

        applied = 0
        skipped = 0
        engine = self.env['auto.reconciliation.engine']
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
                    if not stmt_line.exists() or stmt_line.is_reconciled:
                        skipped += 1; continue
                    if not move_line.exists() or move_line.reconciled:
                        skipped += 1; continue
                    engine._apply_bank_reconciliation_community(stmt_line, move_line)
                    applied += 1
                elif rtype == 'customer_payment':
                    payment = Payment.browse(pair['payment_id'])
                    invoice = Move.browse(pair['invoice_id'])
                    if not payment.exists() or payment.reconciled_invoice_ids:
                        skipped += 1; continue
                    if not invoice.exists() or invoice.payment_state == 'paid':
                        skipped += 1; continue
                    engine._apply_ar_reconciliation(payment, invoice, 'asset_receivable')
                    applied += 1
                elif rtype == 'vendor_payment':
                    payment = Payment.browse(pair['payment_id'])
                    bill = Move.browse(pair['bill_id'])
                    if not payment.exists() or payment.reconciled_bill_ids:
                        skipped += 1; continue
                    if not bill.exists() or bill.payment_state == 'paid':
                        skipped += 1; continue
                    engine._apply_ar_reconciliation(payment, bill, 'liability_payable')
                    applied += 1
                elif rtype == 'intercompany':
                    line = MoveLine.browse(pair['line_id'])
                    counterpart = MoveLine.browse(pair['counterpart_line_id'])
                    if not line.exists() or line.reconciled:
                        skipped += 1; continue
                    if not counterpart.exists() or counterpart.reconciled:
                        skipped += 1; continue
                    self.env['account.move.line'].sudo().browse(
                        [line.id, counterpart.id]
                    ).reconcile()
                    applied += 1
            except Exception as e:
                _logger.warning("Wizard confirm failed for %s pair %s: %s", rtype, pair, str(e))
                skipped += 1

        self.write({'state': 'confirmed', 'skipped_count': skipped})
        deselected = len(all_pairs) - len(pairs)
        msg = _('%d match(es) applied for %s.%s%s') % (
            applied,
            self.company_id.name,
            _(' %d skipped (already reconciled).') % skipped if skipped else '',
            _(' %d deselected by user (not applied).') % deselected if deselected else '',
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconciliation Applied'),
                'message': msg,
                'type': 'warning' if (skipped or deselected) else 'success',
                'sticky': bool(skipped),
            }
        }

    def action_cancel(self):
        return {'type': 'ir.actions.act_window_close'}


class AutoReconciliationWizardLine(models.TransientModel):
    _name = 'auto.reconciliation.wizard.line'
    _description = 'Auto Reconciliation Wizard Line'

    wizard_id = fields.Many2one('auto.reconciliation.wizard', string='Wizard', ondelete='cascade')
    selected = fields.Boolean(string='Include', default=True)
    # Zero-based index into match_pairs_json — links this display row back to
    # its reconciliation pair so action_confirm() can filter by selection.
    pair_index = fields.Integer(string='Pair Index', default=0)
    reconciliation_type = fields.Selection([
        ('bank_statement', 'Bank Statement'),
        ('customer_payment', 'Customer Payment'),
        ('vendor_payment', 'Vendor Payment'),
        ('intercompany', 'Inter-company'),
    ], string='Type')
    description = fields.Char(string='Match Description', readonly=True)
    amount = fields.Float(string='Amount', readonly=True)
    partner_name = fields.Char(string='Partner / Company', readonly=True)
    match_criteria = fields.Char(string='Matched By', readonly=True,
        help='Criteria used to find this match: reference, amount, partner, date_window')
