# -*- coding: utf-8 -*-
import ast
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AutoReconciliationWizard(models.TransientModel):
    _name = 'auto.reconciliation.wizard'
    _description = 'Auto Reconciliation Review Wizard'

    company_id = fields.Many2one('res.company', string='Company', required=True)
    total_preview_count = fields.Integer(string='Total Matches Found', readonly=True)
    match_summary = fields.Text(string='Raw Match Data')  # internal use
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

    @api.depends('match_summary')
    def _compute_line_ids(self):
        """Parse raw match data and populate display lines."""
        for rec in self:
            if not rec.match_summary:
                rec.line_ids = []
                continue
            try:
                matches = ast.literal_eval(rec.match_summary)
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
        """Confirm and execute reconciliation for selected matches."""
        self.ensure_one()
        engine = self.env['auto.reconciliation.engine']
        engine.run_all(company_ids=[self.company_id.id], preview_mode=False)
        self.state = 'confirmed'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reconciliation Applied'),
                'message': _('%d matches confirmed and applied for %s.') % (
                    self.total_preview_count, self.company_id.name
                ),
                'type': 'success',
                'sticky': False,
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
