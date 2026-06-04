# -*- coding: utf-8 -*-
from odoo import models, fields


class ResUsers(models.Model):
    _inherit = 'res.users'

    two_factor_enabled = fields.Boolean(
        string='Enable Two-Factor Authentication (Email OTP)',
        default=False,
        help='When enabled, a one-time password will be sent to your email '
             'every time you log in.',
    )
