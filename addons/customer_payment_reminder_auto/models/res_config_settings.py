from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    payment_reminder_enabled = fields.Boolean(
        related='company_id.payment_reminder_enabled',
        readonly=False,
    )
    payment_reminder_min_outstanding = fields.Monetary(
        related='company_id.payment_reminder_min_outstanding',
        readonly=False,
        currency_field='currency_id',
    )
    payment_reminder_cooldown_days = fields.Integer(
        related='company_id.payment_reminder_cooldown_days',
        readonly=False,
    )
    # Stored as a system parameter (no new column on res.company, so upgrading from
    # the Apps screen works). Inverted on purpose: Odoo deletes a boolean parameter
    # when it is switched off, so "unset" has to mean the default behaviour.
    payment_reminder_disable_followers = fields.Boolean(
        string='Do Not Use Invoice Followers',
        config_parameter='customer_payment_reminder_auto.disable_follower_fallback',
        help='By default, when no earlier invoice email is found, the reminder goes to '
             'the followers of the overdue invoices. Tick to turn that fallback off.',
    )
    payment_reminder_disable_statement = fields.Boolean(
        string='Do Not Attach Statement',
        config_parameter='customer_payment_reminder_auto.disable_statement_attachment',
        help='By default the up-to-date Customer Statement PDF is generated and attached '
             'to every reminder. Tick to send reminders without it.',
    )
    payment_reminder_dry_run = fields.Boolean(
        related='company_id.payment_reminder_dry_run',
        readonly=False,
    )
    payment_reminder_template_id = fields.Many2one(
        related='company_id.payment_reminder_template_id',
        readonly=False,
    )