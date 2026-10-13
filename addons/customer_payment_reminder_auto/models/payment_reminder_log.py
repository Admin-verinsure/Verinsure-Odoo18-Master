from odoo import fields, models


class CustomerPaymentReminderLog(models.Model):
    _name = 'customer.payment.reminder.log'
    _description = 'Customer Payment Reminder Log'
    _order = 'reminder_datetime desc, id desc'

    reminder_datetime = fields.Datetime(
        string='Reminder Timestamp',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    commercial_partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        index=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        ondelete='restrict',
    )
    outstanding_amount = fields.Monetary(
        string='Outstanding Amount',
        currency_field='currency_id',
        required=True,
    )
    recipient_email = fields.Char(string='Recipient Email')
    status = fields.Selection(
        [
            ('sent', 'Sent'),
            ('skipped', 'Skipped'),
            ('failed', 'Failed'),
        ],
        string='Status',
        required=True,
        index=True,
    )
    reason = fields.Text(string='Reason')
    run_token = fields.Char(string='Run Token', index=True)
    is_dry_run = fields.Boolean(string='Dry Run', default=False, index=True)
    mail_mail_id = fields.Many2one('mail.mail', string='Mail')
    mail_state = fields.Selection(
        related='mail_mail_id.state',
        string='Mail Status',
        help='Live status of the email. "Sent" only means the mail server accepted it; '
             'a wrong but well-formed address is only reported later by a bounce.',
    )

    _sql_constraints = [
        (
            'customer_payment_reminder_log_run_unique',
            'unique(run_token, commercial_partner_id, company_id)',
            'Only one reminder log per customer and company is allowed inside the same run.',
        ),
    ]