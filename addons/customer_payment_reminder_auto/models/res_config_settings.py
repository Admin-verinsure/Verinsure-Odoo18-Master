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
    payment_reminder_dry_run = fields.Boolean(
        related='company_id.payment_reminder_dry_run',
        readonly=False,
    )
    payment_reminder_template_id = fields.Many2one(
        related='company_id.payment_reminder_template_id',
        readonly=False,
    )