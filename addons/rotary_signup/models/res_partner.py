# -*- coding: utf-8 -*-
from odoo import models

class ResUsers(models.Model):
    _inherit = "res.users"

    def _signup_create_user(self, values):
        """
        Maintain old signup behavior:
        - Writes club_type into partner
        - Writes rotary_club_id into rotary_org_id
        - Avoids adding new fields to res.partner
        """
        user = super()._signup_create_user(values)
        if not user:
            return user

        partner = user.partner_id.sudo()
        if not partner:
            return user

        # Handle Program/Club Type (legacy behavior)
        club_type = values.get("club_type")
        if club_type:
            try:
                partner.write({"club_type": club_type})
            except Exception as e:
                # Avoid breaking signup if club_type field doesn't exist
                partner._logger = getattr(partner, '_logger', None)
                if partner._logger:
                    partner._logger.warning("Failed to write club_type: %s", e)

        # Handle Rotary Club ID → Rotary Org mapping
        rotary_club_id = values.get("rotary_club_id")
        if rotary_club_id:
            try:
                partner.write({"rotary_org_id": rotary_club_id})
            except Exception as e:
                if partner._logger:
                    partner._logger.warning("Failed to write rotary_org_id: %s", e)

        # Handle Rotary ID or membership number
        rotary_org_id = values.get("rotary_org_id") or values.get("rotary_id")
        if rotary_org_id:
            try:
                partner.write({"rotary_membership_id": str(rotary_org_id)})
            except Exception as e:
                if partner._logger:
                    partner._logger.warning("Failed to write rotary_membership_id: %s", e)

        return user
