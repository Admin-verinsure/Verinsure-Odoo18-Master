from odoo import models

class ResUsers(models.Model):
    _inherit = 'res.partner'

    def _signup_create_user(self, values):
        """Override signup to also save program_type into partner"""
        user = super(ResUsers, self)._signup_create_user(values)
        if values.get('program_type'):
            user.partner_id.sudo().write({
                'club_type': values['program_type']
            })
        return user
