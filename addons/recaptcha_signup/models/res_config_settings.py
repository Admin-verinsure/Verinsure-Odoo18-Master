# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    recaptcha2_public_key = fields.Char("Recaptcha V2 Site Key", config_parameter='recaptcha_signup.public_key', groups='base.group_system')
    recaptcha2_private_key = fields.Char("Recaptcha V2 Secret Key", config_parameter='recaptcha_signup.private_key', groups='base.group_system')
    
    
    recaptcha2_enabled = fields.Boolean("Enable Signup Recaptcha", config_parameter='recaptcha_signup.enabled', groups='base.group_system')
