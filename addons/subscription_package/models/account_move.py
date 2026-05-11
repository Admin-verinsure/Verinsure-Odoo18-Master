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


class AccountMove(models.Model):
    """Inherited sale order model"""
    _inherit = "account.move"

    is_subscription = fields.Boolean(string='Is Subscription', default=False,
                                     help='Is subscription')
    subscription_id = fields.Many2one('subscription.package',
                                      string='Subscription',
                                      help='Choose subscription package')

    @api.model_create_multi
    def create(self, vals_list):
        """Link invoice to subscription via sale order origin.

        FIX: Added guard so that if subscription_id is already present in vals
        (set by the auto-billing cron), we skip the lookup entirely. This
        prevents the two write paths from conflicting with each other.
        FIX: Was updating vals_list[0] unconditionally instead of the current
        rec — broken for any batch create beyond the first record.
        """
        for rec in vals_list:
            # Skip if subscription_id already set (e.g. by auto-billing cron)
            if rec.get('subscription_id'):
                continue
            so_id = self.env['sale.order'].search(
                [('name', '=', rec.get('invoice_origin'))])
            if so_id.is_subscription:
                so_id.subscription_id.start_date = (
                    so_id.subscription_id.next_invoice_date)
                rec.update({
                    'is_subscription': True,
                    'subscription_id': so_id.subscription_id.id,
                })
        return super().create(vals_list)
