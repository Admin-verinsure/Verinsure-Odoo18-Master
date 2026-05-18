# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api, _


class AutoReconciliationConfig(models.Model):
    _name = 'auto.reconciliation.config'
    _description = 'Auto Reconciliation Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(string='Active', default=True)
    enable_bank = fields.Boolean(string='Bank Statements vs Journal Entries', default=True)
    enable_customer = fields.Boolean(string='Customer Payments vs Invoices', default=True)
    enable_vendor = fields.Boolean(string='Vendor Payments vs Bills', default=True)
    enable_intercompany = fields.Boolean(string='Inter-company Transactions', default=True)
    match_by_amount = fields.Boolean(string='Match by Amount', default=True)
    match_by_partner = fields.Boolean(string='Match by Partner', default=True)
    match_by_currency = fields.Boolean(string='Match by Currency', default=True)
    match_by_reference = fields.Boolean(
        string='Match by Payment Reference',
        default=True,
        help='Match the payment reference on the bank transaction (e.g. INV/26-27/0013) '
             'against the invoice number, payment reference, and source document on the '
             'Odoo invoice/bill. This is checked FIRST — it is the strongest signal and '
             'correctly resolves same-amount duplicates.',
    )
    match_by_date_window = fields.Boolean(
        string='Restrict to Date Window',
        default=True,
        help='Only match a bank line to an invoice/move if the invoice date falls within '
             'the configured number of days from the bank transaction date. '
             'Prevents old unpaid invoices from incorrectly absorbing new payments.',
    )
    date_window_days = fields.Integer(
        string='Date Window (days)',
        default=60,
        help='Maximum days between bank transaction date and invoice date for a match '
             'to be accepted. Recommended: 60 for standard NZ payment terms.',
    )
    cron_active = fields.Boolean(string='Enable Scheduled Run', default=True)

    # BUG FIX: Prevent duplicate configs per company — the engine uses limit=1
    # so a second active config would be silently ignored, causing confusing
    # behaviour where toggling a reconciliation type appears to have no effect.
    _sql_constraints = [
        (
            'company_unique',
            'UNIQUE(company_id)',
            'Only one reconciliation configuration per company is allowed. '
            'Please edit the existing configuration instead of creating a new one.',
        ),
    ]

    def action_run_now(self):
        self.ensure_one()
        engine = self.env['auto.reconciliation.engine']
        results = engine.run_all(
            company_ids=[self.company_id.id],
            preview_mode=False,
            triggered_by='manual',
        )
        # BUG FIX: Report actual match count instead of a generic "finished" message.
        company_res = results.get(self.company_id.id, {})
        total = sum(
            company_res.get(k, {}).get('matched_count', 0)
            for k in ['bank_statement', 'customer_payment', 'vendor_payment', 'intercompany']
        )
        if 'error' in company_res:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Reconciliation Error'),
                    'message': company_res['error'],
                    'type': 'danger', 'sticky': True,
                }
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Auto Reconciliation Complete'),
                'message': _('%d match(es) applied for %s.') % (total, self.company_id.name)
                           if total else _('No new matches found for %s.') % self.company_id.name,
                'type': 'success' if total else 'info',
                'sticky': False,
            }
        }

    def action_open_wizard(self):
        """
        Run reconciliation in preview mode, build the wizard with one line per
        match, and open it for the user to review and deselect before confirming.

        Lines are created explicitly via create() after the wizard is saved —
        NOT via a computed field — so Odoo can write back to them when the user
        unchecks a row in the editable list.
        """
        self.ensure_one()
        engine = self.env['auto.reconciliation.engine']
        results = engine.run_all(company_ids=[self.company_id.id], preview_mode=True)
        company_results = results.get(self.company_id.id, {})

        all_matches = []
        for rtype in ['bank_statement', 'customer_payment', 'vendor_payment', 'intercompany']:
            all_matches.extend(company_results.get(rtype, {}).get('matched', []))

        # Build deterministic ID pairs for safe confirm
        id_pairs = []
        for m in all_matches:
            rtype = m.get('type')
            if rtype == 'bank_statement':
                id_pairs.append({
                    'type': 'bank_statement',
                    'statement_line_id': m['statement_line_id'],
                    'move_line_id': m['move_line_id'],
                })
            elif rtype == 'customer_payment':
                id_pairs.append({
                    'type': 'customer_payment',
                    'payment_id': m['payment_id'],
                    'invoice_id': m['invoice_id'],
                })
            elif rtype == 'vendor_payment':
                id_pairs.append({
                    'type': 'vendor_payment',
                    'payment_id': m['payment_id'],
                    'bill_id': m['bill_id'],
                })
            elif rtype == 'intercompany':
                id_pairs.append({
                    'type': 'intercompany',
                    'line_id': m['line_id'],
                    'counterpart_line_id': m['counterpart_line_id'],
                })

        wizard = self.env['auto.reconciliation.wizard'].create({
            'company_id': self.company_id.id,
            'match_summary': json.dumps(all_matches, default=str),
            'match_pairs_json': json.dumps(id_pairs),
            'total_preview_count': len(all_matches),
        })

        # Build display lines explicitly so the list is writable (users can
        # uncheck rows). A computed One2many with no inverse= would raise
        # "Field is not stored and cannot be inversed" on every checkbox click.
        WizardLine = self.env['auto.reconciliation.wizard.line']
        for idx, match in enumerate(all_matches):
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
            WizardLine.create({
                'wizard_id': wizard.id,
                'reconciliation_type': rtype,
                'description': label,
                'amount': match.get('amount', 0.0),
                'partner_name': match.get('partner', match.get('company_from', '')),
                'pair_index': idx,
                'selected': True,
                'match_criteria': match.get('match_criteria', ''),
            })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Review Reconciliation Matches'),
            'res_model': 'auto.reconciliation.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
