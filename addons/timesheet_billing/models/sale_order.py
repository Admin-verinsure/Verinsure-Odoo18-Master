# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    timesheet_billing_project_ids = fields.One2many(
        comodel_name='project.project',
        inverse_name='sale_order_id',
        string='Timesheet Billing Projects',
        help='Projects that bill their timesheets against this order.',
    )
    timesheet_billing_project_count = fields.Integer(
        string='Project Count',
        compute='_compute_timesheet_billing_project_count',
    )

    def _compute_timesheet_billing_project_count(self):
        for order in self:
            order.timesheet_billing_project_count = len(order.timesheet_billing_project_ids)

    def action_view_timesheet_billing_projects(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'project.open_view_project_all'
        )
        action['domain'] = [('sale_order_id', '=', self.id)]
        action['context'] = {'default_sale_order_id': self.id}
        return action
