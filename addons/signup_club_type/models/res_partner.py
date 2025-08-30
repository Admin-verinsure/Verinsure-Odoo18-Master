from odoo import models

class ResUsers(models.Model):
    _inherit = "res.partner"

    def _signup_create_user(self, values):
        user = super()._signup_create_user(values)
        # form posts "program_type" -> write to partner.club_type
        club = values.get("program_type")
        if user and club:
            user.partner_id.sudo().write({"club_type": club})
        return user
