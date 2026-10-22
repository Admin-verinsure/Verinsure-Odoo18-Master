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
    payment_reminder_require_shared_docs = fields.Boolean(
        string='Require Earlier Invoice and Statement Email',
        config_parameter='customer_payment_reminder_auto.require_shared_documents',
        help='Only remind customers who were already emailed an invoice and a statement.',
    )
    # Odoo's res.config.settings validation only accepts a narrow set of field
    # types for config_parameter-backed settings. Date fields raise the RPC error,
    # so we keep the semantic date value as a datetime field and convert it when it
    # is used elsewhere.
    payment_reminder_shared_docs_since = fields.Datetime(
        string='Emails Sent On Or After',
        config_parameter='customer_payment_reminder_auto.shared_documents_since',
        help='Only emails sent on or after this date are searched for the invoice and '
             'statement. Leave empty to search all earlier emails.',
    )
    payment_reminder_require_recent_statement = fields.Boolean(
        string='Require Recently Generated Statement',
        config_parameter='customer_payment_reminder_auto.require_recent_statement',
        help='Only remind customers whose statement was generated (from the Customer '
             'Statement screen) within the number of days below.',
    )
    payment_reminder_statement_recent_days = fields.Integer(
        string='Statement Generated Within (days)',
        config_parameter='customer_payment_reminder_auto.statement_recent_days',
        default=5,
    )
    payment_reminder_statement_start = fields.Datetime(
        string='Default Statement From',
        config_parameter='customer_payment_reminder_auto.statement_default_start',
        help='Start date of the statement attached to reminders when no date is chosen. '
             'Defaults to 1 March 2026.',
    )
    payment_reminder_dry_run = fields.Boolean(
        related='company_id.payment_reminder_dry_run',
        readonly=False,
    )
    payment_reminder_template_id = fields.Many2one(
        related='company_id.payment_reminder_template_id',
        readonly=False,
    )