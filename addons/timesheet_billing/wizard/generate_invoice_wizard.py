# -*- coding: utf-8 -*-
import logging
from collections import OrderedDict

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class GenerateTimesheetInvoiceWizard(models.TransientModel):
    _name = 'timesheet.billing.invoice.wizard'
    _description = 'Generate Timesheet Invoice'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Customer',
        required=True,
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Project',
        domain="[('customer_id', '=', partner_id)] if partner_id else []",
        help='Leave empty to include every billable project for this customer.',
    )
    sale_order_id = fields.Many2one(
        comodel_name='sale.order',
        string='Sales Order',
        domain="[('partner_id', '=', partner_id)] if partner_id else []",
    )
    date_from = fields.Date(string='From Date')
    date_to = fields.Date(string='To Date')
    invoice_date = fields.Date(
        string='Invoice Date',
        default=fields.Date.context_today,
        required=True,
    )
    grouping = fields.Selection(
        selection=[
            ('single', 'Single Line'),
            ('task', 'Per Task'),
            ('employee', 'Per Employee'),
            ('day', 'Per Day'),
            ('product', 'Per Product'),
        ],
        string='Group Invoice Lines By',
        default='task',
        required=True,
    )
    action_after = fields.Selection(
        selection=[
            ('draft', 'Keep as Draft'),
            ('post', 'Validate / Post'),
        ],
        string='After Generation',
        default='draft',
        required=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        compute='_compute_preview',
    )
    timesheet_count = fields.Integer(string='Timesheets Found', compute='_compute_preview')
    total_hours = fields.Float(string='Total Hours', compute='_compute_preview', digits=(16, 2))
    total_amount = fields.Monetary(
        string='Total Amount', compute='_compute_preview', currency_field='currency_id',
    )

    @api.depends('partner_id', 'project_id', 'sale_order_id', 'date_from', 'date_to')
    def _compute_preview(self):
        AnalyticLine = self.env['account.analytic.line']
        for wizard in self:
            wizard.currency_id = self.env.company.currency_id
            if not wizard.partner_id:
                wizard.timesheet_count = 0
                wizard.total_hours = 0.0
                wizard.total_amount = 0.0
                continue
            domain = AnalyticLine._tb_invoiceable_domain(
                project=wizard.project_id,
                sale_order=wizard.sale_order_id,
                partner=wizard.partner_id,
                date_from=wizard.date_from,
                date_to=wizard.date_to,
            )
            lines = AnalyticLine.search(domain)
            wizard.timesheet_count = len(lines)
            wizard.total_hours = sum(lines.mapped('unit_amount'))
            wizard.total_amount = sum(lines.mapped('bill_amount'))
            wizard.currency_id = lines[:1].currency_id or self.env.company.currency_id

    # ------------------------------------------------------------------
    # Onchanges
    # ------------------------------------------------------------------
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.project_id and self.project_id.customer_id != self.partner_id:
            self.project_id = False
        if self.sale_order_id and self.sale_order_id.partner_id != self.partner_id:
            self.sale_order_id = False

    @api.onchange('project_id')
    def _onchange_project_id(self):
        if self.project_id:
            self.partner_id = self.project_id.customer_id
            if self.project_id.sale_order_id:
                self.sale_order_id = self.project_id.sale_order_id

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def _validate_lines(self, lines):
        self.ensure_one()
        errors = []
        for project in lines.project_id:
            if not project.customer_id:
                errors.append(_('Project "%s" has no Customer.', project.name))
            if not project.service_product_id:
                errors.append(_('Project "%s" has no Service Product.', project.name))
            if not project.sale_order_id:
                errors.append(_(
                    'Project "%s" has no Sales Order. Link a Sales Order before invoicing, '
                    'or record the order separately if billing without one is intentional.',
                    project.name,
                ))
        rateless = lines.filtered(lambda l: not l.hourly_rate)
        if rateless:
            errors.append(_(
                'The following timesheet line(s) have no hourly rate resolved: %s.',
                ', '.join(rateless.mapped('name')),
            ))
        already_invoiced = lines.filtered(lambda l: l.billing_status == 'invoiced')
        if already_invoiced:
            errors.append(_(
                'The following timesheet line(s) are already invoiced: %s.',
                ', '.join(already_invoiced.mapped('name')),
            ))
        negative = lines.filtered(lambda l: l.unit_amount < 0)
        if negative:
            errors.append(_('Negative hours found on: %s.', ', '.join(negative.mapped('name'))))
        if errors:
            raise UserError('\n'.join(errors))

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------
    def _group_key(self, line):
        product = line.project_id.service_product_id
        if self.grouping == 'single':
            return (product.id, 'single', False)
        if self.grouping == 'task':
            return (product.id, 'task', line.task_id.id)
        if self.grouping == 'employee':
            return (product.id, 'employee', line.employee_id.id)
        if self.grouping == 'day':
            return (product.id, 'day', line.date)
        if self.grouping == 'product':
            return (product.id, 'product', product.id)
        return (product.id, 'single', False)

    def _group_label(self, grouping, key_value, sample_line):
        product = sample_line.project_id.service_product_id
        if grouping == 'single':
            return product.display_name or _('Timesheet Services')
        if grouping == 'task':
            return sample_line.task_id.name or _('(No Task)')
        if grouping == 'employee':
            return sample_line.employee_id.name or _('(No Employee)')
        if grouping == 'day':
            return fields.Date.to_string(sample_line.date)
        if grouping == 'product':
            return product.display_name
        return product.display_name

    def _build_invoice_line_groups(self, lines):
        """Aggregate timesheet lines into invoice-line groups.
        Returns an OrderedDict keyed by the grouping tuple, each value a
        dict with product, name, hours, amount and the analytic lines.
        A single pass over the (already fetched) recordset -- O(n), no
        extra queries per line, safe for large batches.
        """
        groups = OrderedDict()
        for line in lines:
            key = self._group_key(line)
            if key not in groups:
                groups[key] = {
                    'product': line.project_id.service_product_id,
                    'name': self._group_label(self.grouping, key, line),
                    'hours': 0.0,
                    'amount': 0.0,
                    'lines': self.env['account.analytic.line'],
                }
            groups[key]['hours'] += line.unit_amount
            groups[key]['amount'] += line.bill_amount
            groups[key]['lines'] |= line
        return groups

    # ------------------------------------------------------------------
    # Invoice creation
    # ------------------------------------------------------------------
    def _get_invoice_line_account(self, product):
        accounts = product.product_tmpl_id.get_product_accounts()
        account = accounts.get('income')
        if not account:
            raise UserError(_(
                'Product "%s" has no Income Account configured (directly or via its '
                'category). Set one before generating invoices.', product.display_name,
            ))
        return account

    def _find_sale_order_line(self, project, product):
        if not project.sale_order_id:
            return self.env['sale.order.line']
        return self.env['sale.order.line'].search([
            ('order_id', '=', project.sale_order_id.id),
            ('product_id', '=', product.id),
        ], limit=1)

    def action_generate_invoice(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Customer is required.'))
        if not self.env.context.get('tb_from_cron') and not self.env.user.has_group(
                'timesheet_billing.group_billing_manager'):
            raise UserError(_('Only a Billing Manager can generate invoices.'))

        AnalyticLine = self.env['account.analytic.line']
        domain = AnalyticLine._tb_invoiceable_domain(
            project=self.project_id,
            sale_order=self.sale_order_id,
            partner=self.partner_id,
            date_from=self.date_from,
            date_to=self.date_to,
        )
        lines = AnalyticLine.search(domain)
        if not lines:
            raise UserError(_(
                'No approved, billable, uninvoiced timesheets were found for the selected '
                'criteria and date range.',
            ))

        self._validate_lines(lines)

        groups = self._build_invoice_line_groups(lines)
        total_hours = sum(g['hours'] for g in groups.values())
        if not total_hours:
            raise UserError(_('Nothing to invoice: total hours is zero.'))

        invoice = self._create_invoice(groups)
        self._mark_lines_invoiced(groups, invoice)

        if self.action_after == 'post':
            invoice.action_post()
            if self.env.company.timesheet_billing_auto_email:
                invoice._tb_send_invoice_email()

        _logger.info(
            'Timesheet Billing: generated invoice %s for partner %s (%s lines, %.2f hours).',
            invoice.name or invoice.id, self.partner_id.display_name, len(lines), total_hours,
        )

        return {
            'type': 'ir.actions.act_window',
            'name': _('Customer Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice.id,
        }

    def _create_invoice(self, groups):
        move_lines = []
        for group in groups.values():
            product = group['product']
            account = self._get_invoice_line_account(product)
            hours = group['hours']
            price_unit = (group['amount'] / hours) if hours else 0.0
            taxes = product.taxes_id.filtered(lambda t: t.company_id == self.env.company)
            move_lines.append((0, 0, {
                'product_id': product.id,
                'product_uom_id': product.uom_id.id,
                'name': _('%(label)s (%(hours).2f Hours \u00d7 %(rate)s)', label=group['name'],
                           hours=hours, rate=price_unit),
                'quantity': hours,
                'price_unit': price_unit,
                'account_id': account.id,
                'tax_ids': [(6, 0, taxes.ids)],
            }))

        sale_orders = groups and {
            l.project_id.sale_order_id for g in groups.values() for l in g['lines'] if l.project_id.sale_order_id
        } or set()
        projects = {l.project_id for g in groups.values() for l in g['lines']}
        single_project = list(projects)[0] if len(projects) == 1 else False
        single_order = list(sale_orders)[0] if len(sale_orders) == 1 else False

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.partner_id.id,
            'invoice_date': self.invoice_date,
            'invoice_origin': ', '.join(sorted(o.name for o in sale_orders)) or False,
            'invoice_line_ids': move_lines,
            'timesheet_billing_project_id': single_project.id if single_project else False,
            'timesheet_billing_sale_order_id': single_order.id if single_order else False,
        }
        invoice = self.env['account.move'].create(invoice_vals)
        return invoice

    def _mark_lines_invoiced(self, groups, invoice):
        for inv_line, group in zip(invoice.invoice_line_ids, groups.values()):
            order_line = self._find_sale_order_line(group['lines'][:1].project_id, group['product'])
            group['lines'].with_context(tb_bypass_lock=True).write({
                'invoice_id': invoice.id,
                'invoice_line_id': inv_line.id,
                'sale_order_line_id': order_line.id if order_line else False,
                'billing_status': 'invoiced',
            })
