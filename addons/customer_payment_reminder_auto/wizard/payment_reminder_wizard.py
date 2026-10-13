from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class CustomerPaymentReminderWizard(models.TransientModel):
    _name = 'customer.payment.reminder.wizard'
    _description = 'Send Customer Payment Reminders'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    dry_run = fields.Boolean(
        string='Dry Run (do not send emails)',
        default=lambda self: self.env.company.payment_reminder_dry_run,
        help='Evaluate and log the reminders without sending any email.',
    )
    partner_ids = fields.Many2many(
        'res.partner',
        string='Customers',
        domain=[('customer_rank', '>', 0)],
        help='Leave empty to process every customer with an overdue balance. '
             'The usual rules still apply (threshold, cooldown, valid email, '
             'reminders enabled on the customer).',
    )

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id:
            self.dry_run = self.company_id.payment_reminder_dry_run

    def action_run(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_user'):
            raise AccessError(_('Only accountants can trigger payment reminders.'))
        if self.company_id not in self.env.companies:
            raise UserError(_('You can only run reminders for the companies you are currently allowed to access.'))

        stats = self.env['customer.payment.reminder.service'].sudo().run_manual_payment_reminders(
            company_id=self.company_id.id,
            dry_run=self.dry_run,
            partner_ids=self.partner_ids.ids,
        )
        if stats.get('locked'):
            raise UserError(_(
                'Another payment reminder run is currently in progress. '
                'Please try again in a few minutes.'
            ))

        action = self.env['ir.actions.act_window']._for_xml_id(
            'customer_payment_reminder_auto.action_customer_payment_reminder_log'
        )
        action['domain'] = [('run_token', '=', stats['run_token'])]
        action['context'] = {'search_default_group_by_status': 1}
        message = _(
            'Evaluated: %(evaluated)s, eligible: %(eligible)s, sent: %(sent)s, '
            'skipped: %(skipped)s, failed: %(failed)s.',
            evaluated=stats['evaluated'],
            eligible=stats['eligible'],
            sent=stats['sent'],
            skipped=stats['skipped'],
            failed=stats['failed'],
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Payment Reminders (Dry Run)') if self.dry_run else _('Payment Reminders'),
                'message': message,
                'type': 'warning' if stats['failed'] else 'success',
                'sticky': bool(stats['failed']),
                'next': action,
            },
        }
