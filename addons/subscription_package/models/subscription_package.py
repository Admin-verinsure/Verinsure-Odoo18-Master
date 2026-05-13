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
from markupsafe import Markup
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.exceptions import UserError


class SubscriptionPackage(models.Model):
    """Subscription Package Model"""
    _name = 'subscription.package'
    _description = 'Subscription Package'
    _rec_name = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """ Read all the stages and display it in the kanban view,
            even if it is empty."""
        stages_ids = stages.sudo()._search([], order=stages._order)
        return stages.browse(stages_ids)

    def _default_stage_id(self):
        """Setting default stage"""
        rec = self.env['subscription.package.stage'].search([], limit=1,
                                                            order='sequence ASC')
        return rec.id if rec else None

    name = fields.Char(string='Name', default="New", compute='_compute_name',
                       store=True, required=True,
                       help='Choose the name for the subscription package.')
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 help='Select the customer associated with '
                                      'this record.')
    partner_invoice_id = fields.Many2one('res.partner',
                                         help='Select the invoice address '
                                              'associated with this record.',
                                         string='Invoice Address',
                                         related='partner_id')
    partner_shipping_id = fields.Many2one('res.partner',
                                          help="Add shipping/service address",
                                          string='Shipping/Service Address',
                                          related='partner_id')
    plan_id = fields.Many2one('subscription.package.plan',
                              string='Subscription Plan',
                              help="Choose the subscription package plan")
    start_date = fields.Date(string='Period Start Date',
                             help='Add the period start date',
                             ondelete='restrict')
    date_started = fields.Date(string='Subsciption Start date',
                               help='Add the Subscription package start date',
                               ondelete='restrict', readonly=True)
    next_invoice_date = fields.Date(string='Next Invoice Date',
                                    store=True, help='Add next invoice date',
                                    compute="_compute_next_invoice_date",
                                    inverse="_inverse_next_invoice_date")
    company_id = fields.Many2one('res.company', string='Company',
                                 help='Select the company',
                                 default=lambda self: self.env.company,
                                 required=True)
    user_id = fields.Many2one('res.users', string='Sales Person',
                              help='Add the Sales person',
                              default=lambda self: self.env.user)
    sale_order_id = fields.Many2one('sale.order', string="Sale Order",
                                    help='Select the sale order', copy=False)
    is_to_renew = fields.Boolean(string='To Renew', copy=True,
                                 help='Is subscription package is renew')
    tag_ids = fields.Many2many('account.account.tag', string='Tags',
                               help='Add the tags')
    stage_id = fields.Many2one('subscription.package.stage', string='Stage',
                               default=lambda self: self._default_stage_id(),
                               index=True,
                               group_expand='_read_group_stage_ids',
                               help='Subscription Package stage', copy=False)
    invoice_count = fields.Integer(string='Invoices',
                                   help='Subscription package invoice count',
                                   compute='_compute_invoice_count')
    so_count = fields.Integer(string='Sales',
                              help='subscription package sales count',
                              compute='_compute_sale_count')
    description = fields.Text(string='Description',
                              help='Subscription package description')
    analytic_account_id = fields.Many2one('account.analytic.account',
                                          help='Choose the analytic account',
                                          string='Analytic Account')
    product_line_ids = fields.One2many('subscription.package.product.line',
                                       'subscription_id', ondelete='restrict',
                                       string='Products Line',
                                       help='Subscription package product line')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                  readonly=True, default=lambda
            self: self.env.company.currency_id, help='Add Currency')
    current_stage = fields.Char(string='Current Stage', default='Draft',
                                help='Current stage of the '
                                     'subscription package. '
                                     'This field is computed based on '
                                     'the associated stage_id.',
                                store=True, compute='_compute_current_stage')
    reference_code = fields.Char(string='Reference',
                                 help='This field represents the '
                                      'reference code associated '
                                      'with the record.')
    is_closed = fields.Boolean(string="Closed", default=False,
                               help='Is Closed')
    close_reason_id = fields.Many2one('subscription.package.stop',
                                      help='The reason for c'
                                           'losing the subscription package.',
                                      string='Close Reason')
    closed_by = fields.Many2one('res.users', string='Closed By',
                                help="The user responsible "
                                     "for closing the record")
    close_date = fields.Date(string='Closed on',
                             help="The date on which the record was closed")
    stage_category = fields.Selection(related='stage_id.category',
                                      help="The category associated with "
                                           "the current stage of the record. ",
                                      store=True)
    invoice_mode = fields.Selection(related="plan_id.invoice_mode",
                                    help="The invoice mode "
                                         "associated with the plan.")
    total_recurring_price = fields.Float(string='Untaxed Amount',
                                         help="The total recurring "
                                              "price excluding taxes.",
                                         compute='_compute_total_recurring_price',
                                         store=True)
    tax_total = fields.Float("Taxes", readonly=True,
                             help="The total amount of "
                                  "taxes associated with the record")
    total_with_tax = fields.Monetary("Total Recurring Price", readonly=True,
                                     help="The total recurring "
                                          "price including taxes")
    recurrence_period_id = fields.Many2one("recurrence.period",
                                           string="Recurrence Period")
    sale_order_count = fields.Integer(string='Sale Order Count',
                                      help="The count of associated "
                                           "sale orders for this record.")

    def _valid_field_parameter(self, field, name):
        """Check the validity of a field parameter for a specific field."""
        if name == 'ondelete':
            return True
        return super(SubscriptionPackage,
                     self)._valid_field_parameter(field, name)

    def _compute_invoice_count(self):
        """Calculate invoice count for this subscription.

        FIX: Removed @api.depends('invoice_count') — a field cannot depend on
        itself (infinite recompute loop). Removed the invoices.write()
        side-effect that was previously inside this compute method. Compute
        methods must be pure — writing to other records from a compute causes
        re-computation loops and transaction errors. The subscription_id stamp
        on invoices is handled by account_move.create() and the billing cron.
        FIX: Scoped to 'for rec in self' so batch calls work correctly.
        """
        for rec in self:
            rec.invoice_count = self.env['account.move'].search_count(
                [('subscription_id', '=', rec.id),
                 ('move_type', 'in', ('out_invoice', 'out_refund'))])

    @api.depends('sale_order_id')
    def _compute_sale_count(self):
        """Calculate sale order count based on subscription package.

        FIX: Changed depends from 'so_count' (self-reference → infinite loop)
        to 'sale_order_id'. Added 'for rec in self' for correct batch handling.
        """
        for rec in self:
            rec.so_count = self.env['sale.order'].search_count(
                [('id', '=', rec.sale_order_id.id)])

    @api.depends('stage_id')
    def _compute_current_stage(self):
        """ It displays current stage for subscription package """
        for rec in self:
            rec.current_stage = rec.env['subscription.package.stage'].search(
                [('id', '=', rec.stage_id.id)]).category

    @api.depends('start_date', 'plan_id')
    def _compute_next_invoice_date(self):
        """Compute next invoice date from start_date + renewal_time.

        FIX: Was previously looping over ALL subscriptions via search([]) on
        every start_date change of any single record, causing a full-table
        recompute. Now correctly scoped to 'for sub in self'. Also added
        plan_id to depends so changing the plan re-triggers the compute.
        """
        for sub in self:
            if sub.start_date and sub.plan_id.renewal_time:
                sub.next_invoice_date = sub.start_date + relativedelta(
                    days=sub.plan_id.renewal_time)
            else:
                sub.next_invoice_date = False

    def _inverse_next_invoice_date(self):
        """Inverse function for next invoice date — allows manual override."""
        pass

    def button_invoice_count(self):
        """ It displays invoice based on subscription package """
        return {
            'name': 'Invoices',
            'domain': [('subscription_id', '=', self.id)],
            'view_type': 'form',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
            'context': {
                "create": False
            }
        }

    def button_sale_count(self):
        """ It displays sale order based on subscription package """
        return {
            'name': 'Products',
            'domain': [('id', '=', self.sale_order_id.id)],
            'view_type': 'form',
            'res_model': 'sale.order',
            'view_mode': 'list,form',
            'type': 'ir.actions.act_window',
            'context': {
                "create": False
            }
        }

    def button_close(self):
        """ Button for subscription close wizard """
        return {
            'name': "Subscription Close Reason",
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'subscription.close',
            'target': 'new'
        }

    def button_start_date(self):
        """Button to start subscription package"""
        stage_id = (self.env['subscription.package.stage'].search([
            ('category', '=', 'progress')], limit=1).id)
        for rec in self:
            if len(rec.env['subscription.package.stage'].search(
                    [('category', '=', 'draft')])) > 1:
                raise UserError(
                    _('More than one stage is having category "Draft". '
                      'Please change category of stage to "In Progress", '
                      'only one stage is allowed to have category "Draft"'))
            else:
                if not rec.product_line_ids:
                    raise UserError("Empty order lines !! Please add the "
                                    "subscription product.")
                else:
                    if rec.sale_order_id:
                        rec.sale_order_id.write({'subscription_id': rec.id,
                                                 'is_subscription': True})
                        for line in rec.sale_order_id.order_line.filtered(
                                lambda x: x.product_template_id.is_subscription == True):
                            line.qty_to_invoice = line.product_uom_qty
                    rec.write(
                        {'stage_id': stage_id,
                         'date_started': fields.Date.today(),
                         'start_date': fields.Date.today()})

    def button_sale_order(self):
        """Button to create sale order.

        FIX: Removed 'id': self.sale_order_count from the create() call —
        passing an explicit 'id' to create() attempts to force a specific
        integer ID which is undefined behavior in Odoo 18 and causes integrity
        errors. sale_order_count is a computed count field, not an ID.
        FIX: The orders search was using sale_order_count (a count integer)
        as a record ID — replaced with sale_order_id.id.
        """
        this_products_line = []
        for rec in self.product_line_ids:
            rec_list = [0, 0, {'product_id': rec.product_id.id,
                               'product_uom_qty': rec.product_qty,
                               'discount': rec.discount}]
            this_products_line.append(rec_list)
        orders = self.env['sale.order'].search(
            [('id', '=', self.sale_order_id.id),
             ('invoice_status', '=', 'no')])
        if orders:
            for order in orders:
                order.action_confirm()
        so_id = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'partner_invoice_id': self.partner_id.id,
            'partner_shipping_id': self.partner_id.id,
            'is_subscription': True,
            'subscription_id': self.id,
            'order_line': this_products_line
        })
        self.sale_order_id = so_id
        return {
            'name': _('Sales Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'domain': [('id', '=', so_id.id)],
            'view_mode': 'list,form',
            'context': {
                "create": False
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        """Generate sequence and mark partner as active subscription.

        FIX: Moved 'return' outside the for loop. Previously the return was
        inside the loop, causing only the first record in a batch create to
        be processed — all subsequent records were silently dropped.
        FIX: Changed 'if vals.get("reference_code", "New") is False' to
        'if not vals.get("reference_code")' — the original condition never
        triggered because get() with a default of "New" never returns False.
        """
        for vals in vals_list:
            partner = self.env['res.partner'].search(
                [('id', '=', vals.get('partner_id'))])
            partner.is_active_subscription = True
            if not vals.get('reference_code'):
                vals['reference_code'] = self.env['ir.sequence'].next_by_code(
                    'sequence.reference.code') or 'New'
        return super().create(vals_list)

    @api.depends('reference_code', 'plan_id', 'partner_id')
    def _compute_name(self):
        """It displays record name as combination of short code, reference
        code and partner name """
        for rec in self:
            plan_id = self.env['subscription.package.plan'].search(
                [('id', '=', rec.plan_id.id)])
            if plan_id.short_code and rec.reference_code:
                rec.name = plan_id.short_code + '/' + rec.reference_code + '-' + rec.partner_id.name

    def set_close(self):
        """ Button to close subscription package """
        stage = self.env['subscription.package.stage'].search(
            [('category', '=', 'closed')], limit=1).id
        for sub in self:
            values = {'stage_id': stage, 'is_to_renew': False}
            sub.write(values)
        return True

    def send_renew_alert_mail(self, today, renew_date, sub_id):
        """The function is used to send a renewal alert email and mark the
        subscription for renewal if today is the renewal date."""
        if today == renew_date:
            self.env.ref(
                'subscription_package'
                '.mail_template_subscription_renew').send_mail(
                sub_id, force_send=True)
            subscription = self.env['subscription.package'].browse(sub_id)
            subscription.write({'is_to_renew': True})
            return True
        else:
            return False

    def find_renew_date(self, next_invoice, date_started, end):
        """The function is used to calculate the renewal date, end date,
        and close date based on subscription details."""
        if end == 0:
            end_date = next_invoice
            difference = (next_invoice - date_started).days / 10
            renew_date = next_invoice - relativedelta(
                days=difference)
            close_date = next_invoice
        else:
            end_date = fields.Date.add(date_started,
                                       days=end)
            close = date_started + relativedelta(days=end)
            difference = (close - date_started).days / 10
            renew_date = close - relativedelta(
                days=difference)
            close_date = close

        data = {'renew_date': renew_date,
                'end_date': end_date,
                'close_date': close_date}
        return data

    def close_limit_cron(self):
        """Check renew date and close date. Send renewal alert email when
        approaching renewal date. Auto-close subscription if renewal limit
        is exceeded.

        FIX: Removed the invoice creation block that previously existed here.
        Invoice creation is now owned exclusively by run_auto_subscription_billing()
        to prevent duplicate invoices being generated on the same next_invoice_date.
        FIX: Removed start_date write from this cron — advancing start_date here
        triggers _compute_next_invoice_date to push next_invoice_date forward
        before the billing cron runs, causing the billing cron's filter to miss
        the record entirely (date-race). The billing cron now owns start_date.
        FIX: Replaced self.user_id (wrong in cron context) with self.env.user
        for closed_by assignment.
        """
        pending_subscriptions = self.env['subscription.package'].search(
            [('stage_category', '=', 'progress')])
        today_date = fields.Date.today()
        pending_subscription = False
        for pending_subscription in pending_subscriptions:
            # FIX: Guard — skip if next_invoice_date or date_started is not
            # set. find_renew_date does date arithmetic on both values and
            # raises TypeError if either is False/None. next_invoice_date is
            # set to False by the auto-close block below, so subscriptions
            # that were just closed in the same cron run would crash here
            # without this guard.
            if not pending_subscription.next_invoice_date:
                continue
            if not pending_subscription.date_started:
                continue

            get_dates = self.find_renew_date(
                pending_subscription.next_invoice_date,
                pending_subscription.date_started,
                pending_subscription.plan_id.days_to_end)
            renew_date = get_dates['renew_date']
            end_date = get_dates['end_date']
            pending_subscription.close_date = get_dates['close_date']

            # Send renewal alert when invoice date arrives.
            # start_date advancement and invoice creation are handled
            # exclusively by run_auto_subscription_billing.
            if today_date == pending_subscription.next_invoice_date:
                new_date = self.find_renew_date(
                    pending_subscription.next_invoice_date,
                    pending_subscription.date_started,
                    pending_subscription.plan_id.days_to_end)
                pending_subscription.write(
                    {'close_date': new_date['close_date'],
                     'is_to_renew': False})
                self.send_renew_alert_mail(today_date,
                                           new_date['renew_date'],
                                           pending_subscription.id)

            # Auto-close if renewal limit exceeded
            if (today_date == end_date and
                    pending_subscription.plan_id.limit_choice != 'manual'):
                display_msg = Markup(
                    "<h5><i>The renewal limit has been exceeded "
                    "today for this subscription based on the "
                    "current subscription plan.</i></h5>")
                pending_subscription.message_post(body=display_msg)
                pending_subscription.is_closed = True
                reason = self.env['subscription.package.stop'].search(
                    [('name', '=', 'Renewal Limit Exceeded')]).id
                pending_subscription.close_reason_id = reason
                # FIX: self.user_id is wrong in cron context
                pending_subscription.closed_by = self.env.user
                pending_subscription.close_date = fields.Date.today()
                stage = self.env['subscription.package.stage'].search(
                    [('category', '=', 'closed')], limit=1).id
                values = {'stage_id': stage, 'is_to_renew': False,
                          'next_invoice_date': False}
                pending_subscription.write(values)

            self.send_renew_alert_mail(today_date, renew_date,
                                       pending_subscription.id)

        return dict(pending=pending_subscription)

    @api.depends('product_line_ids.total_amount',
                 'product_line_ids.price_total', 'product_line_ids.tax_ids')
    def _compute_total_recurring_price(self):
        """ The compute function used to calculate recurring price """
        for record in self:
            total_recurring = 0
            total_tax = 0.0
            for line in record.product_line_ids:
                if line.total_amount != line.price_total:
                    line_tax = line.price_total - line.total_amount
                    total_tax += line_tax
                total_recurring += line.total_amount
            record['total_recurring_price'] = total_recurring
            record['tax_total'] = total_tax
            total_with_tax = total_recurring + total_tax
            record['total_with_tax'] = total_with_tax

    def action_renew(self):
        """ The function is used to perform the renewal
        action for the subscription package."""
        return self.button_sale_order()

    def _get_billing_order_lines(self):
        """Build sale order line values from subscription product lines.
        Returns a list of (0, 0, vals) tuples ready for order_line field."""
        order_lines = []
        for line in self.product_line_ids:
            if not line.product_id:
                continue
            order_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.product_qty,
                'price_unit': line.unit_price,
                'discount': line.discount,
                'tax_id': [(6, 0, line.tax_ids.ids)],
            }))
        return order_lines

    def _compute_next_billing_date(self):
        """Compute the next invoice date after a billing cycle completes.

        FIX: Now uses the renewal_period field to apply true calendar-aware
        relativedelta increments (months, years) instead of flat days.
        Previously all periods were stored as approximate days (28 days per
        month, 364 days per year) causing billing dates to drift over time.
        """
        self.ensure_one()
        if not self.next_invoice_date or not self.plan_id:
            return False
        period = self.plan_id.renewal_period
        value = max(self.plan_id.renewal_value or 1, 1)
        if period == 'days':
            delta = relativedelta(days=value)
        elif period == 'weeks':
            delta = relativedelta(weeks=value)
        elif period == 'months':
            delta = relativedelta(months=value)
        elif period == 'years':
            delta = relativedelta(years=value)
        else:
            delta = relativedelta(days=value)
        return self.next_invoice_date + delta

    def _is_duplicate_invoice_exists(self, billing_date):
        """Check whether a posted invoice already exists for this subscription
        on the given billing date to guarantee idempotency on re-runs."""
        self.ensure_one()
        return self.env['account.move'].search_count([
            ('subscription_id', '=', self.id),
            ('invoice_date', '=', billing_date),
            ('move_type', '=', 'out_invoice'),
            ('state', 'not in', ('cancel',)),
        ]) > 0

    def run_auto_subscription_billing(self):
        """Automated billing cron entry point.

        Finds all active (in-progress) subscriptions whose next_invoice_date
        has arrived, then for each one:
          1. Skips if invoice_mode is 'manual'.
          2. Skips if no product lines are configured.
          3. Skips if no customer is set.
          4. Skips if a non-cancelled invoice already exists for that date
             (idempotency guard).
          5. Creates and confirms a Sale Order.
          6. Generates and posts the invoice via _create_invoices().
          7. Emails the posted invoice to the customer automatically.
          8. Advances next_invoice_date by one true calendar billing cycle.
          9. Advances start_date to the billed date.
         10. Posts a chatter message with the outcome.

        FIX: Scoped to cron user's companies (multi-company safe).
        FIX: Uses a savepoint per subscription — one failure does not abort
             the entire batch; the cursor stays valid for subsequent records.
        FIX: Added manual invoice mode guard (was missing entirely).
        NEW: Invoice is automatically emailed to the customer after posting.
        """
        today = fields.Date.today()

        # FIX: scope to the cron user's accessible companies so multi-company
        # instances don't bill subscriptions belonging to other companies.
        due_subscriptions = self.env['subscription.package'].search([
            ('stage_category', '=', 'progress'),
            ('next_invoice_date', '<=', today),
            ('is_closed', '=', False),
            ('company_id', 'in', self.env.companies.ids),
        ])

        billed_count = 0
        skipped_count = 0

        for sub in due_subscriptions:
            # FIX: savepoint per subscription — rolls back only this record on
            # failure, leaving the cursor valid for the rest of the batch.
            try:
                with self.env.cr.savepoint():
                    # Guard — skip manual invoice mode plans
                    if sub.plan_id.invoice_mode == 'manual':
                        sub.message_post(
                            body=Markup(_(
                                "<b>Auto-billing skipped:</b> Plan is set "
                                "to manual invoicing. Please invoice "
                                "manually.")))
                        skipped_count += 1
                        continue

                    # Guard: skip subscriptions with no billable products
                    if not sub.product_line_ids:
                        sub.message_post(
                            body=Markup(_(
                                "<b>Auto-billing skipped:</b> No product "
                                "lines configured on this subscription.")))
                        skipped_count += 1
                        continue

                    # Guard: skip subscriptions with no partner
                    if not sub.partner_id:
                        sub.message_post(
                            body=Markup(_(
                                "<b>Auto-billing skipped:</b> No customer "
                                "set on this subscription.")))
                        skipped_count += 1
                        continue

                    billing_date = sub.next_invoice_date or today

                    # Idempotency: skip if invoice already exists for this period
                    if sub._is_duplicate_invoice_exists(billing_date):
                        sub.message_post(
                            body=Markup(_(
                                "<b>Auto-billing skipped:</b> Invoice "
                                "already exists for billing date %s.")
                                ) % billing_date)
                        skipped_count += 1
                        continue

                    order_lines = sub._get_billing_order_lines()
                    if not order_lines:
                        skipped_count += 1
                        continue

                    # Step 1: Create and confirm Sale Order
                    sale_order = self.env['sale.order'].with_user(
                        SUPERUSER_ID).create({
                        'partner_id': sub.partner_id.id,
                        'partner_invoice_id': sub.partner_id.id,
                        'partner_shipping_id': sub.partner_id.id,
                        'is_subscription': True,
                        'subscription_id': sub.id,
                        'company_id': sub.company_id.id,
                        'user_id': sub.user_id.id or self.env.uid,
                        'order_line': order_lines,
                    })
                    sale_order.action_confirm()

                    # Step 2: Generate invoice from the confirmed sale order
                    invoices = sale_order._create_invoices(final=False)
                    if not invoices:
                        raise UserError(
                            _("Invoice generation returned no records for "
                              "subscription %s.") % sub.name)

                    # Step 3: Stamp and post the invoice
                    invoices.write({
                        'subscription_id': sub.id,
                        'is_subscription': True,
                        'invoice_date': billing_date,
                    })
                    invoices.action_post()

                    # Step 4: Email the posted invoice to the customer
                    # FIX: Respect the send_invoice_email toggle on the plan.
                    email_sent = False
                    if sub.plan_id.send_invoice_email:
                        email_sent = sub._send_invoice_by_email(invoices)

                    # Step 5: Advance the billing cycle
                    next_date = sub._compute_next_billing_date()
                    sub.write({
                        'sale_order_id': sale_order.id,
                        'next_invoice_date': next_date,
                        'start_date': billing_date,
                        'is_to_renew': False,
                    })

                    if email_sent:
                        email_note = Markup(
                            _("Invoice emailed to <b>%s</b>.") %
                            sub.partner_id.email)
                    else:
                        email_note = Markup(_(
                            "&#9888; Invoice email could not be sent "
                            "(no email address on customer)."))

                    sub.message_post(
                        body=Markup(_(
                            "<b>Auto-billing completed</b> for period "
                            "<b>%s</b>.<br/>"
                            "Sale Order: <b>%s</b> | Invoice: <b>%s</b> | "
                            "Next billing date: <b>%s</b><br/>%s"
                        )) % (billing_date, sale_order.name,
                              ', '.join(invoices.mapped('name')),
                              next_date, email_note))

                    billed_count += 1

            except Exception as exc:
                # Savepoint already rolled back the DB changes for this sub.
                sub = self.env['subscription.package'].browse(sub.id)
                sub.message_post(
                    body=Markup(_(
                        "<b>Auto-billing failed</b> on %s.<br/>"
                        "<i>Error: %s</i><br/>"
                        "Please review and bill manually if required."
                    )) % (today, str(exc)))

        return {
            'billed': billed_count,
            'skipped': skipped_count,
            'total': len(due_subscriptions),
        }

    def _send_invoice_by_email(self, invoices):
        """Send posted invoices to the customer using the standard Odoo
        invoice email template ('account.email_template_edi_invoice').

        The template renders the invoice PDF as an attachment automatically.
        Falls back to generating the PDF report manually if the EDI template
        is not available.

        Returns True if email was dispatched, False if partner has no email.
        """
        self.ensure_one()
        if not self.partner_id.email:
            return False

        template = self.env.ref(
            'account.email_template_edi_invoice', raise_if_not_found=False)

        for invoice in invoices:
            if template:
                template.send_mail(
                    invoice.id,
                    force_send=True,
                    email_layout_xmlid=(
                        'mail.mail_notification_layout_with_responsible_signature'),
                )
            else:
                # Fallback: render PDF manually and post via chatter
                report = self.env.ref('account.account_invoices',
                                      raise_if_not_found=False)
                if not report:
                    continue
                pdf_content, _ = report._render_qweb_pdf([invoice.id])
                attachment = self.env['ir.attachment'].create({
                    'name': '%s.pdf' % (invoice.name or 'Invoice'),
                    'type': 'binary',
                    'datas': pdf_content,
                    'res_model': 'account.move',
                    'res_id': invoice.id,
                    'mimetype': 'application/pdf',
                })
                invoice.message_post(
                    body=_("Please find your invoice attached."),
                    subject=_("Invoice %s") % invoice.name,
                    partner_ids=[self.partner_id.id],
                    attachment_ids=[attachment.id],
                    subtype_xmlid='mail.mt_comment',
                )
        return True
