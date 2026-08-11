# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    timesheet_billing_project_id = fields.Many2one(
        comodel_name='project.project',
        string='Timesheet Billing Project',
        copy=False,
        readonly=True,
        help='Set automatically when this invoice is generated from the '
             'Timesheet Billing wizard or a scheduled invoicing action.',
    )
    timesheet_billing_sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Originating Sales Order',
        copy=False,
        readonly=True,
    )
    timesheet_ids = fields.One2many(
        comodel_name='account.analytic.line',
        inverse_name='invoice_id',
        string='Billed Timesheets',
        readonly=True,
    )
    timesheet_count = fields.Integer(
        string='Timesheet Count',
        compute='_compute_timesheet_count',
    )

    @api.depends('timesheet_ids')
    def _compute_timesheet_count(self):
        for move in self:
            move.timesheet_count = len(move.timesheet_ids)

    def action_view_billed_timesheets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Billed Timesheets'),
            'res_model': 'account.analytic.line',
            'view_mode': 'list,form',
            'domain': [('invoice_id', '=', self.id)],
        }

    def _tb_send_invoice_email(self):
        """Email posted invoices to the customer using the standard
        Accounting invoice template. Silently skipped (with a log entry)
        if the template is not available, e.g. `account` mail data was
        customized/removed - this must never block invoice generation.
        """
        template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
        if not template:
            return
        for move in self.filtered(lambda m: m.state == 'posted'):
            template.send_mail(move.id, force_send=False)
