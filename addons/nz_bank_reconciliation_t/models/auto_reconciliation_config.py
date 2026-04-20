# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api, _


class AutoReconciliationConfig(models.Model):
    _name = 'auto.reconciliation.config'
    _description = 'Auto Reconciliation Configuration'
    _rec_name = 'company_id'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(string='Active', default=True)

    # Reconciliation toggles
    enable_bank = fields.Boolean(string='Bank Statements vs Journal Entries', default=True)
    enable_customer = fields.Boolean(string='Customer Payments vs Invoices', default=True)
    enable_vendor = fields.Boolean(string='Vendor Payments vs Bills', default=True)
    enable_intercompany = fields.Boolean(string='Inter-company Transactions', default=True)

    # Matching rules
    match_by_amount = fields.Boolean(string='Match by Exact Amount', default=True)
    match_by_partner = fields.Boolean(string='Match by Partner', default=True)
    match_by_currency = fields.Boolean(string='Match by Currency', default=True)

    # Cron settings
    cron_active = fields.Boolean(string='Enable Scheduled Run', default=True)

    def action_run_now(self):
        """Manually trigger reconciliation for this company."""
        self.ensure_one()
        engine = self.env['auto.reconciliation.engine']
        engine.run_all(company_ids=[self.company_id.id], preview_mode=False, triggered_by='manual')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Auto Reconciliation Complete'),
                'message': _('Reconciliation finished for %s.') % self.company_id.name,
                'type': 'success',
                'sticky': False,
            }
        }

    def action_open_wizard(self):
        """
        Open the review wizard before confirming reconciliation.

        CRITICAL FIX 3: We now pass two separate datasets to the wizard:
          - match_summary: human-readable list (JSON) for display in wizard lines
          - match_pairs_json: structured ID pairs (JSON) that confirm() applies
            deterministically — only these exact records, re-validated at confirm time.
        """
        self.ensure_one()
        engine = self.env['auto.reconciliation.engine']
        results = engine.run_all(company_ids=[self.company_id.id], preview_mode=True)

        company_results = results.get(self.company_id.id, {})

        # Flatten all human-readable match dicts for display
        all_matches = []
        for rtype in ['bank_statement', 'customer_payment', 'vendor_payment', 'intercompany']:
            all_matches.extend(company_results.get(rtype, {}).get('matched', []))

        # Build deterministic ID pairs for safe confirm (CRITICAL FIX 3)
        # Each pair contains only the IDs needed to re-fetch and apply the match.
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

        return {
            'type': 'ir.actions.act_window',
            'name': _('Review Reconciliation Matches'),
            'res_model': 'auto.reconciliation.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
