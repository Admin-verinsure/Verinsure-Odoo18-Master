from odoo import models

class ResUsers(models.Model):
    _inherit = "res.users"

    def _signup_create_user(self, values):
        user = super()._signup_create_user(values)
        if not user:
            return user

        club_type = values.get("club_type")
        if club_type:
            user.partner_id.sudo().write({"club_type": club_type})

        rotary_club_id = values.get("rotary_club_id")
        if rotary_club_id:
            user.partner_id.sudo().write({"rotary_org_id": rotary_club_id})

        return user
