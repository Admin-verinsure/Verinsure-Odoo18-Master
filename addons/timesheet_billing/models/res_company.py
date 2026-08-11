# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    timesheet_billing_default_rate = fields.Monetary(
        string='Default Timesheet Hourly Rate',
        currency_field='currency_id',
        help='Fallback hourly rate used when no rate is defined on the '
             'timesheet, task, project, or product. Last step of the rate '
             'resolution cascade.',
        default=0.0,
    )
    timesheet_billing_auto_email = fields.Boolean(
        string='Auto-email Generated Invoices',
        default=False,
        help='When enabled, invoices created by the Timesheet Billing '
             'wizard or scheduled actions are emailed to the customer '
             'automatically after posting.',
    )
