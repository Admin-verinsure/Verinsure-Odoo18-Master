from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    payment_reminder_enabled = fields.Boolean(
        string='Enable Payment Reminders',
        default=False,
        help='When enabled, the scheduled job can send automated payment reminders for this company.',
    )
    payment_reminder_min_outstanding = fields.Monetary(
        string='Minimum Outstanding Amount',
        currency_field='currency_id',
        default=100.0,
        help='Customers must owe at least this amount in the company currency to qualify.',
    )
    payment_reminder_cooldown_days = fields.Integer(
        string='Reminder Cooldown (Days)',
        default=7,
        help='Minimum number of days between reminders for the same customer and company.',
    )
    payment_reminder_dry_run = fields.Boolean(
        string='Dry Run Mode',
        default=True,
        help='When enabled, the cron evaluates and logs reminders but does not send emails.',
    )
    payment_reminder_template_id = fields.Many2one(
        'mail.template',
        string='Payment Reminder Template',
        domain="[('model', '=', 'res.partner')]",
        help='Optional override template used for payment reminders.',
    )