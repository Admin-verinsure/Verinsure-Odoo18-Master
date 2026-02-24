# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AkahuImportWizard(models.TransientModel):
    _name = 'akahu.import.wizard'
    _description = 'Import Akahu Bank Transactions'

    journal_id = fields.Many2one(
        'account.journal',
        string="Bank Journal",
        domain=[('type', '=', 'bank')],
        required=True,
        default=lambda self: self.env['account.journal'].search([('type', '=', 'bank')], limit=1),
    )
    days_back = fields.Integer(string="Days to Fetch", default=90)
    run_reconcile = fields.Boolean(string="Auto-Reconcile After Import", default=True)
    amount_tolerance = fields.Float(string="Amount Tolerance", default=0.50,
                                    help="Allowed difference when matching open items.")
    require_text_hint = fields.Boolean(string="Require Text Hint", default=False,
                                       help="Only reconcile when the statement text appears in the invoice/bill references.")

    def action_import_transactions(self):
        self.ensure_one()
        if self.days_back <= 0:
            raise UserError(_("Days to Fetch must be positive."))

        service = self.env['akahu.bank.statement'].sudo()

        imp_result = service.import_akahu_transactions(
            journal_id=self.journal_id.id,
            days_back=self.days_back,
            tz_name=self.env.user.tz or "UTC",
        )

        rec_result = {}
        if self.run_reconcile:
            rec_result = service.auto_reconcile_bank_lines(
                journal_id=self.journal_id.id,
                max_days=max(7, min(self.days_back, 90)),  # reasonable window
                amount_tolerance=self.amount_tolerance,
                require_text_hint=self.require_text_hint,
            )

        msg = _("Import complete: %(created)d created, %(skipped)d skipped.") % imp_result
        if rec_result:
            msg += _(" Auto-reconcile: %(reconciled)d done, %(ambiguous)d ambiguous, %(missing)d unmatched.") % rec_result

        # Pop a friendly notification, then show the latest statement for this journal
        last_statement = self.env['account.bank.statement'].search(
            [('journal_id', '=', self.journal_id.id)],
            order='date desc, id desc',
            limit=1
        )
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('Akahu Import'), 'message': msg, 'sticky': False},
        }
        if last_statement:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'account.bank.statement',
                'view_mode': 'form',
                'res_id': last_statement.id,
                'target': 'current',
                'context': {'default_journal_id': self.journal_id.id},
            }
        return action
