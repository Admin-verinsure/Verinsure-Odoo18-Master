# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    timesheet_hourly_rate = fields.Monetary(
        string='Timesheet Hourly Rate',
        currency_field='currency_id',
        help='Hourly rate used by Timesheet Billing when this product is '
             'set as a project/task service product and no more specific '
             'rate (timesheet/task/project) is available. Falls back to '
             'List Price, then to the company default rate, when left at '
             'zero.',
    )

    def _tb_is_billable_service(self):
        """Return True if the product can be used as a Timesheet Billing
        service product (billed by time on the analytic line).
        Kept as a single method so the "service only" rule lives in one
        place and can be reused by constraints, domains, and the wizard.
        """
        self.ensure_one()
        return self.type == 'service'
