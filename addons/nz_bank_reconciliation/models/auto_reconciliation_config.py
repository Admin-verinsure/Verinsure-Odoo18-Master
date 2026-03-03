# -*- coding: utf-8 -*-
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
        results = engine.run_all(company_ids=[self.company_id.id], preview_mode=False)

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
        """Open the review wizard before confirming reconciliation."""
        self.ensure_one()
        engine = self.env['auto.reconciliation.engine']
        # Run in preview mode to get match candidates
        results = engine.run_all(company_ids=[self.company_id.id], preview_mode=True)

        # Collect all matches into a flat list for wizard display
        all_matches = []
        for rtype in ['bank_statement', 'customer_payment', 'vendor_payment', 'intercompany']:
            all_matches.extend(results[self.company_id.id].get(rtype, {}).get('matched', []))

        wizard = self.env['auto.reconciliation.wizard'].create({
            'company_id': self.company_id.id,
            'match_summary': str(all_matches),
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
