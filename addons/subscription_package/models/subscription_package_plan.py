# -*- coding: utf-8 -*-
#############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: SREERAG PM (<https://www.cybrosys.com>)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
#############################################################################
from odoo import api, fields, models


class SubscriptionPackagePlan(models.Model):
    _name = 'subscription.package.plan'
    _description = 'Subscription Package Plan'

    name = fields.Char(string='Plan Name', required=True,
                       help='The name of the subscription plan.')
    renewal_value = fields.Integer(string='Renewal',
                                   default=1,
                                   help='The number of periods between renewals.')
    renewal_period = fields.Selection([('days', 'Day(s)'),
                                       ('weeks', 'Week(s)'),
                                       ('months', 'Month(s)'),
                                       ('years', 'Year(s)')],
                                      default='months',
                                      help='Select the unit of time for the '
                                           'renewal period of the '
                                           'subscription plan.')
    renewal_time = fields.Integer(string='Renewal Time Interval (days)',
                                  compute='_compute_renewal_time',
                                  store=True,
                                  help='The computed renewal time interval '
                                       'in days for the subscription plan.')
    limit_choice = fields.Selection([('ones', 'Ones'),
                                     ('manual', 'Until Closed Manually'),
                                     ('custom', 'Custom')],
                                    default='ones',
                                    help='Select the limit choice for the '
                                         'subscription plan, specifying how '
                                         'long it will be active.')
    limit_count = fields.Integer(string='Custom Renewal Limit',
                                 default=1,
                                 help='Specify the custom renewal limit for '
                                      'the subscription plan. This field is '
                                      'relevant when the "Limit Choice" is '
                                      'set to "Custom".')
    days_to_end = fields.Integer(string='Days End', readonly=True,
                                 compute='_compute_days_to_end', store=True,
                                 help="Subscription ending date")
    invoice_mode = fields.Selection([('manual', 'Manually'),
                                     ('draft_invoice', 'Auto (Post & Send)')],
                                    default='draft_invoice',
                                    help='Select the invoice mode for the '
                                         'subscription plan, specifying '
                                         'whether invoices are generated '
                                         'manually or posted and sent automatically.')
    send_invoice_email = fields.Boolean(
        string='Auto-send Invoice by Email',
        default=True,
        help='When enabled, the auto-billing cron will email the posted '
             'invoice to the customer automatically after each billing cycle.')
    journal_id = fields.Many2one('account.journal', string='Journal',
                                 domain="[('type', '=', 'sale')]")
    company_id = fields.Many2one('res.company', string='Company', store=True,
                                 default=lambda self: self.env.company)
    short_code = fields.Char(string='Short Code')
    terms_and_conditions = fields.Text(string='Terms and Conditions')
    product_count = fields.Integer(string='Products',
                                   compute='_compute_product_count')
    subscription_count = fields.Integer(string='Subscriptions',
                                        compute='_compute_subscription_count')

    def _compute_product_count(self):
        """Calculate product count based on subscription plan.

        FIX: Removed @api.depends('product_count') — a field cannot depend on
        itself. Added 'for rec in self' for correct batch handling.
        """
        for rec in self:
            rec.product_count = self.env['product.product'].search_count(
                [('subscription_plan_id', '=', rec.id)])

    def _compute_subscription_count(self):
        """Calculate subscription count based on subscription plan.

        FIX: Removed @api.depends('subscription_count') — a field cannot
        depend on itself. Added 'for rec in self' for correct batch handling.
        """
        for rec in self:
            rec.subscription_count = self.env[
                'subscription.package'].search_count(
                [('plan_id', '=', rec.id)])

    @api.depends('renewal_value', 'renewal_period')
    def _compute_renewal_time(self):
        """Calculate renewal time in days based on renewal value and period.

        FIX: renewal_value is now an Integer field (was Char), eliminating the
        int() cast that crashed on non-numeric input. Negative/zero values are
        clamped to 1. Approximate day counts kept for renewal_time (used only
        for initial next_invoice_date); subsequent billing cycles use the
        calendar-aware _compute_next_billing_date() with relativedelta.
        """
        for rec in self:
            value = max(rec.renewal_value or 1, 1)
            if rec.renewal_period == 'days':
                rec.renewal_time = value
            elif rec.renewal_period == 'weeks':
                rec.renewal_time = value * 7
            elif rec.renewal_period == 'months':
                rec.renewal_time = value * 30
            elif rec.renewal_period == 'years':
                rec.renewal_time = value * 365
            else:
                rec.renewal_time = value
            if rec.name:
                rec.short_code = str(rec.name[0:3]).upper()

    @api.depends('renewal_time', 'limit_count', 'limit_choice')
    def _compute_days_to_end(self):
        """Calculate days to end for subscription plan based on limit count.

        FIX: Added limit_choice to depends. Changed if/if/if → if/elif/elif
        so only one branch executes. Clamped limit_count to minimum of 1.
        """
        for rec in self:
            if rec.limit_choice == 'ones':
                rec.days_to_end = rec.renewal_time
            elif rec.limit_choice == 'manual':
                rec.days_to_end = 0
            elif rec.limit_choice == 'custom':
                count = max(rec.limit_count or 1, 1)
                rec.days_to_end = rec.renewal_time * count

    def button_product_count(self):
        """ It displays products based on subscription plan """
        return {
            'name': 'Products',
            'res_model': 'product.product',
            'domain': [('subscription_plan_id', '=', self.id)],
            'view_type': 'form',
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
            'context': {
                'default_is_subscription': True,
            },
        }

    def button_sub_count(self):
        """ It displays subscriptions based on subscription plan """
        return {
            'name': 'Subscriptions',
            'domain': [('plan_id', '=', self.id)],
            'view_type': 'form',
            'res_model': 'subscription.package',
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
        }

    def name_get(self):
        """ It displays record name as combination of short code and
        plan name """
        res = []
        for rec in self:
            res.append((rec.id, '%s - %s' % (rec.short_code, rec.name)))
        return res
