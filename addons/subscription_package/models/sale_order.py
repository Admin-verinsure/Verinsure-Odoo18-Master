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


class SaleOrder(models.Model):
    """ This class is used to inherit sale order"""
    _inherit = 'sale.order'

    subscription_count = fields.Integer(string='Subscriptions',
                                        compute='_compute_subscription_count',
                                        help='Subscriptions count')
    is_subscription = fields.Boolean(string='Is Subscription', default=False,
                                     help='Is subscription')
    subscription_id = fields.Many2one('subscription.package',
                                      string='Subscription',
                                      help='Choose the subscription')
    sub_reference = fields.Char(string="Sub Reference Code", store=True,
                                compute="_compute_reference_code",
                                help='Subscription Reference Code')

    @api.model_create_multi
    def create(self, vals_list):
        """It displays subscription in sale order.

        FIX: return is now OUTSIDE the loop so all records in a batch create
        are processed, not just the first one.
        """
        for vals in vals_list:
            if vals.get('is_subscription'):
                vals.update({
                    'is_subscription': True,
                    'subscription_id': vals.get('subscription_id'),
                })
        return super().create(vals_list)

    @api.depends('subscription_id')
    def _compute_reference_code(self):
        """It displays subscription reference code.

        FIX: Added 'for rec in self' for correct batch handling.
        FIX: Removed int() cast on subscription_id.id — Many2one .id is
        already an int or False; int(False) raises TypeError.
        """
        for rec in self:
            rec.sub_reference = self.env['subscription.package'].search(
                [('id', '=', rec.subscription_id.id)]).reference_code

    def action_confirm(self):
        """Update subscription stage when a sale order is manually confirmed.

        FIX: Removed 'start_date' write — billing cron owns start_date
        advancement to avoid a date-race that pushed next_invoice_date forward
        before the cron could run. Setting start_date here from a manually
        confirmed SO is the wrong place for it.
        FIX: datetime.datetime.today() returned a datetime object but
        start_date is a Date field — this caused a type mismatch error.
        FIX: self.search([('id', '=', sale_order.id)]) was looking up by
        sale_order.id (a Many2one) not an integer — replaced with a direct
        state read from the already-browsed record.
        """
        res = super().action_confirm()
        if self.is_subscription and self.subscription_id:
            # Only move the subscription to 'progress' stage on a manual SO
            # confirmation (i.e. not the auto-billing cron SOs, which have
            # already-active subscriptions). Avoid touching start_date here.
            sale_order = self.subscription_id.sale_order_id
            if sale_order and sale_order.state in ('sale', 'done'):
                stage = self.env['subscription.package.stage'].search(
                    [('category', '=', 'progress')], limit=1).id
                self.subscription_id.write({
                    'stage_id': stage,
                    'is_to_renew': False,
                })
        return res

    @api.depends('subscription_id')
    def _compute_subscription_count(self):
        """Compute count of subscriptions associated with the sale order.

        FIX: Removed @api.depends('subscription_count') — a field cannot
        depend on itself (infinite recompute loop).
        FIX: Added 'for rec in self' for correct batch handling.
        """
        for rec in self:
            subscription_count = self.env[
                'subscription.package'].sudo().search_count(
                [('sale_order_id', '=', rec.id)])
            rec.subscription_count = subscription_count if subscription_count > 0 else 0

    def button_subscription(self):
        """Open the subscription packages associated with the sale order."""
        return {
            'name': 'Subscription',
            'sale_order_id': False,
            'domain': [('sale_order_id', '=', self.id)],
            'view_type': 'form',
            'res_model': 'subscription.package',
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
            'context': {
                "create": False
            }
        }

    def _action_confirm(self):
        """Confirm the sale order and create subscriptions for subscription
        products.

        FIX: If this SO was created by the auto-billing cron it already carries
        a subscription_id, so we must NOT create another draft subscription.
        The original guard (subscription_count != 1) failed for auto-billing
        SOs because each new SO has 0 linked subscriptions, causing a ghost
        draft subscription to be created on every billing cycle.
        """
        # Guard: SO created by auto-billing already belongs to an existing
        # subscription — skip new subscription creation entirely.
        if self.is_subscription and self.subscription_id:
            return super()._action_confirm()

        if self.subscription_count != 1:
            if self.order_line:
                for line in self.order_line:
                    if line.product_id.is_subscription:
                        this_products_line = []
                        rec_list = [0, 0, {'product_id': line.product_id.id,
                                           'product_qty': line.product_uom_qty,
                                           'unit_price': line.price_unit}]
                        this_products_line.append(rec_list)
                        self.env['subscription.package'].create(
                            {
                                'sale_order_id': self.id,
                                'reference_code': self.env[
                                    'ir.sequence'].next_by_code(
                                    'sequence.reference.code'),
                                'start_date': fields.Date.today(),
                                'stage_id': self.env.ref(
                                    'subscription_package.draft_stage').id,
                                'partner_id': self.partner_id.id,
                                'plan_id': line.product_id.subscription_plan_id.id,
                                'product_line_ids': this_products_line
                            })
        return super()._action_confirm()
