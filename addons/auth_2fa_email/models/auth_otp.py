# -*- coding: utf-8 -*-
import random
import string
from datetime import datetime, timedelta
from odoo import models, fields, api


class AuthOtp(models.Model):
    _name = 'auth.otp'
    _description = 'Authentication OTP Token'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True, ondelete='cascade', index=True
    )
    otp_code = fields.Char(string='OTP Code', size=6, required=True)
    expiry_time = fields.Datetime(string='Expiry Time', required=True)
    is_used = fields.Boolean(string='Used', default=False)
    created_at = fields.Datetime(string='Created At', default=fields.Datetime.now)

    @api.model
    def generate_otp(self, user_id):
        """Generate a fresh 6-digit OTP for the given user, invalidating any prior ones."""
        # Invalidate all previous tokens for this user
        self.sudo().search([('user_id', '=', user_id), ('is_used', '=', False)]).write(
            {'is_used': True}
        )
        code = ''.join(random.choices(string.digits, k=6))
        expiry = datetime.now() + timedelta(minutes=10)
        token = self.sudo().create({
            'user_id': user_id,
            'otp_code': code,
            'expiry_time': expiry,
        })
        return token

    @api.model
    def verify_otp(self, user_id, code):
        """
        Verify the submitted OTP code.
        Returns True if valid, False otherwise.
        """
        token = self.sudo().search([
            ('user_id', '=', user_id),
            ('otp_code', '=', code),
            ('is_used', '=', False),
            ('expiry_time', '>=', datetime.now()),
        ], limit=1)
        if token:
            token.write({'is_used': True})
            return True
        return False

    @api.model
    def cleanup_expired(self):
        """Cron-friendly method to remove old/expired OTP records."""
        cutoff = datetime.now() - timedelta(hours=24)
        self.sudo().search([
            ('created_at', '<', fields.Datetime.to_string(cutoff))
        ]).unlink()
