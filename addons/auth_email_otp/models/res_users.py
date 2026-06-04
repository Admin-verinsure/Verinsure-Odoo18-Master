# -*- coding: utf-8 -*-
"""
res.users extension
===================
Adds `email_otp_enabled` Boolean field.

Design decisions:
- Field is groups-protected: only administrators can toggle it.
- We intentionally do NOT override `_check_credentials` here because
  Odoo 18's auth flow calls `_check_credentials` inside the DB session
  and it is not the right place to inject an async challenge flow.
  The 2FA interception happens at the HTTP controller layer instead.
"""
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    email_otp_enabled = fields.Boolean(
        string='Enable Email 2FA',
        default=False,
        groups='base.group_erp_manager',
        help=(
            'When enabled, this user must verify a One-Time Password '
            'sent to their email address after entering their password. '
            'Only administrators can modify this setting.'
        ),
    )
