# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ProjectProject(models.Model):
    _inherit = 'project.project'

    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sales Order',
        copy=False,
        tracking=True,
        domain="[('partner_id', '=', customer_id)] if customer_id else []",
        help='Sales Order this project bills its timesheets against. '
             'Optional: a project can be billed without an order using a '
             'directly-priced service product.',
    )
    service_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Service Product',
        copy=False,
        tracking=True,
        domain="[('type', '=', 'service')]",
        help='Service product used to price and invoice this project\'s '
             'timesheets. Must be a Service-type product.',
    )
    customer_id = fields.Many2one(
        comodel_name='res.partner',
        string='Timesheet Billing Customer',
        related='partner_id',
        store=True,
        readonly=False,
        help='Customer billed for this project\'s timesheets. Mirrors the '
             'project\'s own Customer field.',
    )
    hourly_rate = fields.Monetary(
        string='Project Hourly Rate',
        currency_field='currency_id',
        tracking=True,
        help='Default hourly rate for this project. Used when a timesheet '
             'or task does not define a more specific rate.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_currency_id',
        store=True,
        readonly=True,
    )
    billing_type = fields.Selection(
        selection=[
            ('hourly', 'Hourly'),
            ('fixed', 'Fixed Price'),
            ('time_material', 'Time & Material'),
        ],
        string='Billing Type',
        default='hourly',
        tracking=True,
        required=True,
        help='Hourly: invoice exactly the approved hours logged.\n'
             'Fixed Price: informational only, hours are tracked but not '
             'the basis for invoicing.\n'
             'Time & Material: hourly billing plus the ability to add '
             'material/expense lines on the same order (handled by Sales).',
    )

    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_invoice_count',
    )
    billable_hours = fields.Float(
        string='Billable Hours',
        compute='_compute_timesheet_hours',
        store=True,
        digits=(16, 2),
        help='Sum of hours on billable timesheet lines for this project.',
    )
    invoiced_hours = fields.Float(
        string='Invoiced Hours',
        compute='_compute_timesheet_hours',
        store=True,
        digits=(16, 2),
        help='Sum of hours on billable timesheet lines already linked to '
             'a customer invoice.',
    )
    remaining_hours = fields.Float(
        string='Remaining Hours to Invoice',
        compute='_compute_timesheet_hours',
        store=True,
        digits=(16, 2),
        help='Approved, billable hours not yet linked to any invoice.',
    )

    @api.depends('sale_order_id', 'sale_order_id.currency_id', 'company_id.currency_id')
    def _compute_currency_id(self):
        for project in self:
            project.currency_id = (
                project.sale_order_id.currency_id
                or project.company_id.currency_id
                or self.env.company.currency_id
            )

    def _compute_invoice_count(self):
        AnalyticLine = self.env['account.analytic.line']
        # single grouped read_group instead of one query per project
        groups = AnalyticLine._read_group(
            domain=[('project_id', 'in', self.ids), ('invoice_id', '!=', False)],
            groupby=['project_id', 'invoice_id'],
        )
        counts = {}
        for project, _invoice in groups:
            counts[project.id] = counts.get(project.id, 0) + 1
        for project in self:
            project.invoice_count = counts.get(project.id, 0)

    @api.depends(
        'timesheet_ids.unit_amount',
        'timesheet_ids.billable',
        'timesheet_ids.billing_status',
    )
    def _compute_timesheet_hours(self):
        AnalyticLine = self.env['account.analytic.line']
        billable_groups = AnalyticLine._read_group(
            domain=[('project_id', 'in', self.ids), ('billable', '=', True)],
            groupby=['project_id'],
            aggregates=['unit_amount:sum'],
        )
        billable_map = {project.id: total for project, total in billable_groups}

        invoiced_groups = AnalyticLine._read_group(
            domain=[
                ('project_id', 'in', self.ids),
                ('billable', '=', True),
                ('billing_status', '=', 'invoiced'),
            ],
            groupby=['project_id'],
            aggregates=['unit_amount:sum'],
        )
        invoiced_map = {project.id: total for project, total in invoiced_groups}

        for project in self:
            billable = billable_map.get(project.id, 0.0)
            invoiced = invoiced_map.get(project.id, 0.0)
            project.billable_hours = billable
            project.invoiced_hours = invoiced
            project.remaining_hours = billable - invoiced

    @api.constrains('service_product_id')
    def _check_service_product_type(self):
        for project in self:
            if project.service_product_id and not project.service_product_id._tb_is_billable_service():
                raise ValidationError(_(
                    'The service product "%(product)s" on project "%(project)s" must '
                    'be of type Service to be used for timesheet billing.',
                    product=project.service_product_id.display_name,
                    project=project.name,
                ))

    def action_view_timesheet_billing_invoices(self):
        self.ensure_one()
        invoice_ids = self.env['account.analytic.line'].search([
            ('project_id', '=', self.id), ('invoice_id', '!=', False),
        ]).invoice_id.ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', invoice_ids)],
        }

    def action_view_timesheet_billing_timesheets(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Timesheets'),
            'res_model': 'account.analytic.line',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def _tb_resolve_hourly_rate(self):
        """Rate resolution cascade, project level: Project rate -> Product
        list price -> Company default rate."""
        self.ensure_one()
        if self.hourly_rate:
            return self.hourly_rate
        if self.service_product_id:
            if self.service_product_id.timesheet_hourly_rate:
                return self.service_product_id.timesheet_hourly_rate
            if self.service_product_id.list_price:
                return self.service_product_id.list_price
        return self.company_id.timesheet_billing_default_rate or self.env.company.timesheet_billing_default_rate

    def action_view_timesheet_billing_sale_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Order'),
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': self.sale_order_id.id,
        }
