from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    payment_reminder_enabled = fields.Boolean(
        string='Automatic Payment Reminders',
        default=True,
        help='Disable this to exclude the customer from automated payment reminders.',
    )
    payment_reminder_email_override = fields.Char(
        string='Reminder Email Override',
        help='Optional email address used instead of the partner email for payment reminders.',
    )

    def action_open_payment_reminder_logs(self):
        self.ensure_one()
        action = self.env.ref(
            'customer_payment_reminder_auto.action_customer_payment_reminder_log'
        ).read()[0]
        action['domain'] = [('commercial_partner_id', '=', self.commercial_partner_id.id)]
        action['context'] = {
            'default_commercial_partner_id': self.commercial_partner_id.id,
            'search_default_group_by_company_id': 1,
        }
        return action

    def action_run_payment_reminder_dry_run(self):
        self.ensure_one()
        stats = self.env['customer.payment.reminder.service'].sudo().run_manual_payment_reminder(
            partner_id=self.commercial_partner_id.id,
            company_id=self.env.company.id,
            dry_run=True,
        )
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
                'title': _('Payment Reminder Dry Run'),
                'message': message,
                'type': 'info',
                'sticky': False,
            },
        }