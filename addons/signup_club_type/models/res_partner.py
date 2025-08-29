from odoo import models

class ResUsers(models.Model):
    _inherit = 'res.users'

    def _signup_create_user(self, values):
        """Override signup to also save club_type into partner"""
        user = super(ResUsers, self)._signup_create_user(values)
        if values.get('club_type'):
            user.partner_id.sudo().write({
                'club_type': values['club_type']
            })
        return user
