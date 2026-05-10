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
    match_summary = fields.Text(string='Raw Match Data')
    # CRITICAL FIX 3: Stores exact ID pairs captured at preview time.
    # confirm() applies only these — engine never re-runs from scratch.
    match_pairs_json = fields.Text(string='Match Pairs JSON')
    line_ids = fields.One2many(
        'auto.reconciliation.wizard.line', 'wizard_id',
        string='Match Lines', compute='_compute_line_ids', store=False,
    )
    state = fields.Selection([
        ('preview', 'Preview'), ('confirmed', 'Confirmed'),
    ], default='preview')
    skipped_count = fields.Integer(string='Skipped', readonly=True, default=0)

    @api.depends('match_summary')
    def _compute_line_ids(self):
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
                    label = 'Bank: %s ↔ %s' % (match.get('statement_line_name', ''), match.get('move_line_name', ''))
                elif rtype == 'customer_payment':
                    label = 'Customer: %s ↔ %s' % (match.get('payment_name', ''), match.get('invoice_name', ''))
                elif rtype == 'vendor_payment':
                    label = 'Vendor: %s ↔ %s' % (match.get('payment_name', ''), match.get('bill_name', ''))
                elif rtype == 'intercompany':
                    label = 'IC: %s (%s) ↔ %s (%s)' % (
                        match.get('line_name', ''), match.get('company_from', ''),
                        match.get('counterpart_line_name', ''), match.get('company_to', ''),
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
        CRITICAL FIX 3: Apply only the specific ID pairs from preview time.
        Re-validates each record is still unreconciled before applying.
        Items reconciled in the meantime (e.g. by cron) are safely skipped.
        """
        self.ensure_one()
        if not self.match_pairs_json:
            raise UserError(_('No preview data found. Please close and run Preview again.'))
        try:
            pairs = json.loads(self.match_pairs_json)
        except Exception:
            raise UserError(_('Preview data is corrupt. Please close and run Preview again.'))

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
                    (line | counterpart).reconcile()
                    applied += 1
            except Exception as e:
                _logger.warning("Wizard confirm failed for %s pair %s: %s", rtype, pair, str(e))
                skipped += 1

        self.write({'state': 'confirmed', 'skipped_count': skipped})
        msg = _('%d match(es) applied for %s.%s') % (
            applied, self.company_id.name,
            _(' %d skipped (already reconciled).') % skipped if skipped else ''
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconciliation Applied'),
                'message': msg,
                'type': 'warning' if skipped else 'success',
                'sticky': bool(skipped),
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
