# In your existing model file

from odoo import models

class ResUsers(models.Model):
    _inherit = "res.users"  # Corrected model inheritance

    def _signup_create_user(self, values):
        user = super()._signup_create_user(values)
        
        # form posts "program_type" -> write to partner.club_type
        club = values.get("program_type")
        if user and club:
            user.partner_id.sudo().write({"club_type": club})

        # Add logic for Rotary ID
        rotary_id_value = values.get("rotary_id")
        if user and rotary_id_value:
            user.partner_id.sudo().write({"rotary_org_id": rotary_id_value})

        return user