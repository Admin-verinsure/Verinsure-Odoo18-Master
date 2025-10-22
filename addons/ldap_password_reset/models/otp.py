from odoo import api, fields, models

class OTP(models.Model):
    _name = "otp"
    _description = "One-Time Password for password reset"
    _order = "create_date desc"

    user_id = fields.Many2one("res.users", required=True, ondelete="cascade")
    otp_code = fields.Char(required=True, index=True)
    expiration_time = fields.Datetime(required=True, index=True)
