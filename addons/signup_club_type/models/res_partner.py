from odoo import models

class ResUsers(models.Model):
    _inherit = 'res.users'

    def _signup_create_user(self, values):
        # create user first
        user = super()._signup_create_user(values)
        # save selection into the partner
        club_type = values.get('club_type')
        if club_type:
            user.partner_id.sudo().write({"club_type": club_type})
        return user

