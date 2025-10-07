# res_partner.py
from odoo import models

class ResUsers(models.Model):
    _inherit = "res.users"

    def _signup_create_user(self, values):
        user = super()._signup_create_user(values)

        # form posts "club_type" (not program_type)
        club = values.get("club_type")
        if user and club:
            user.partner_id.sudo().write({"club_type": club})

        # form posts "rotary_club_id" (not rotary_id)
        rotary_id_value = values.get("rotary_club_id")
        if user and rotary_id_value:
            user.partner_id.sudo().write({"rotary_org_id": rotary_id_value})

        return user
