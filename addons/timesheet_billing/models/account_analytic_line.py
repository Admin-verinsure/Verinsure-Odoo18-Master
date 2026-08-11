# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AccountAnalyticLine(models.Model):
    _inherit = 'account.analytic.line'

    billable = fields.Boolean(
        string='Billable',
        default=True,
        tracking=True,
        help='Whether this timesheet line can be invoiced to the customer. '
             'Defaults from the task, then the project.',
    )
    billing_status = fields.Selection(
        selection=[
            ('non_billable', 'Non-Billable'),
            ('to_invoice', 'To Invoice'),
            ('partially_invoiced', 'Partially Invoiced'),
            ('invoiced', 'Invoiced'),
        ],
        string='Billing Status',
        default='to_invoice',
        copy=False,
        tracking=True,
        readonly=True,
        help='Automatically maintained. "Partially Invoiced" is used when '
             'a line is split across invoice runs (e.g. hours edited after '
             'a partial invoice was posted).',
    )
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Invoice',
        copy=False,
        readonly=True,
        tracking=True,
        help='Customer invoice this timesheet line was billed on.',
    )
    invoice_line_id = fields.Many2one(
        comodel_name='account.move.line',
        string='Invoice Line',
        copy=False,
        readonly=True,
    )
    sale_order_line_id = fields.Many2one(
        comodel_name='sale.order.line',
        string='Sales Order Line',
        copy=False,
        readonly=True,
        help='Order line this timesheet line was billed against, when the '
             'project is linked to a Sales Order.',
    )
    hourly_rate = fields.Monetary(
        string='Hourly Rate',
        currency_field='currency_id',
        help='Rate used to price this line. Highest priority in the rate '
             'resolution cascade: set this to override the task/project/'
             'product/company rate.',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        compute='_compute_tb_currency_id',
        store=True,
        readonly=True,
    )
    bill_amount = fields.Monetary(
        string='Bill Amount',
        currency_field='currency_id',
        compute='_compute_bill_amount',
        store=True,
        help='unit_amount (hours) x hourly_rate, computed automatically.',
    )
    approved = fields.Boolean(
        string='Approved',
        default=False,
        copy=False,
        tracking=True,
        help='Approved timesheets can be selected by the invoice wizard. '
             'Unapproved billable timesheets are excluded from billing.',
    )
    approved_by = fields.Many2one(
        comodel_name='res.users',
        string='Approved By',
        copy=False,
        readonly=True,
        tracking=True,
    )
    approved_date = fields.Datetime(
        string='Approved On',
        copy=False,
        readonly=True,
        tracking=True,
    )

    @api.depends('project_id.currency_id', 'company_id.currency_id')
    def _compute_tb_currency_id(self):
        for line in self:
            line.currency_id = (
                line.project_id.currency_id
                or line.company_id.currency_id
                or self.env.company.currency_id
            )

    @api.depends('unit_amount', 'hourly_rate')
    def _compute_bill_amount(self):
        for line in self:
            line.bill_amount = line.unit_amount * line.hourly_rate

    # ------------------------------------------------------------------
    # Defaults / rate resolution
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._tb_apply_defaults(vals)
        lines = super().create(vals_list)
        return lines

    def _tb_apply_defaults(self, vals):
        """Populate billable flag and hourly_rate on creation when not
        explicitly provided, following the rate resolution cascade:
        Timesheet (explicit vals) > Task > Project > Product > Company.
        """
        task = None
        project = None
        if vals.get('task_id'):
            task = self.env['project.task'].browse(vals['task_id'])
            project = task.project_id
        elif vals.get('project_id'):
            project = self.env['project.project'].browse(vals['project_id'])

        if 'billable' not in vals:
            if task:
                vals['billable'] = task.billable
            elif project:
                vals['billable'] = True
            # else: keep the field default (True) for non-project lines

        if not vals.get('hourly_rate'):
            rate = 0.0
            if task:
                rate = task._tb_resolve_hourly_rate()
            elif project:
                rate = project._tb_resolve_hourly_rate()
            if rate:
                vals['hourly_rate'] = rate

        if 'billing_status' not in vals:
            vals['billing_status'] = 'to_invoice' if vals.get('billable') else 'non_billable'
        return vals

    # ------------------------------------------------------------------
    # Locking / duplicate invoicing protection
    # ------------------------------------------------------------------
    def write(self, vals):
        if not self.env.context.get('tb_bypass_lock'):
            locked_fields = {
                'unit_amount', 'amount', 'date', 'employee_id', 'project_id',
                'task_id', 'product_id', 'hourly_rate', 'billable',
            }
            if locked_fields.intersection(vals.keys()):
                invoiced = self.filtered(lambda l: l.billing_status == 'invoiced')
                if invoiced:
                    raise UserError(_(
                        'The following timesheet line(s) are already invoiced '
                        'and cannot be modified: %s. Create a credit note on '
                        'the related invoice(s) instead.',
                        ', '.join(invoiced.mapped('name')),
                    ))
        return super().write(vals)

    def unlink(self):
        invoiced = self.filtered(lambda l: l.billing_status == 'invoiced')
        if invoiced:
            raise UserError(_(
                'You cannot delete timesheet line(s) that are already '
                'invoiced: %s.', ', '.join(invoiced.mapped('name')),
            ))
        return super().unlink()

    @api.constrains('unit_amount')
    def _check_positive_hours(self):
        for line in self:
            if line.unit_amount < 0:
                raise ValidationError(_(
                    'Timesheet "%s" cannot have negative hours.', line.name or line.id,
                ))

    # ------------------------------------------------------------------
    # Approval workflow
    # ------------------------------------------------------------------
    def action_approve_timesheets(self):
        if not self.env.user.has_group('timesheet_billing.group_timesheet_manager') \
                and not self.env.user.has_group('timesheet_billing.group_billing_manager'):
            raise UserError(_('Only a Timesheet Manager or Billing Manager can approve timesheets.'))
        self.write({
            'approved': True,
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
        })
        for line in self:
            line.message_post(body=_(
                'Timesheet approved by %(user)s.', user=self.env.user.display_name,
            ))

    def action_reset_approval(self):
        if not self.env.user.has_group('timesheet_billing.group_timesheet_manager') \
                and not self.env.user.has_group('timesheet_billing.group_billing_manager'):
            raise UserError(_('Only a Timesheet Manager or Billing Manager can reset approval.'))
        non_invoiced = self.filtered(lambda l: l.billing_status != 'invoiced')
        non_invoiced.write({'approved': False, 'approved_by': False, 'approved_date': False})

    # ------------------------------------------------------------------
    # Search domain helper used by the wizard / dashboard / crons
    # ------------------------------------------------------------------
    @api.model
    def _tb_invoiceable_domain(self, project=None, sale_order=None, partner=None,
                                date_from=None, date_to=None):
        domain = [
            ('billable', '=', True),
            ('approved', '=', True),
            ('billing_status', 'in', ('to_invoice', 'partially_invoiced')),
            ('unit_amount', '>', 0),
        ]
        if project:
            domain.append(('project_id', '=', project.id))
        if sale_order:
            domain.append(('project_id.sale_order_id', '=', sale_order.id))
        if partner:
            domain.append(('project_id.customer_id', '=', partner.id))
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        return domain
