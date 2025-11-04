# -*- coding: utf-8 -*-
from odoo import models, fields

class ResPartner(models.Model):
    _inherit = "res.partner"

    # Add missing Rotary fields (used by signup & filters)
    is_rotary_club = fields.Boolean(string="Is Rotary Club", default=False)
    club_name = fields.Char(string="Club Name")
    program_type = fields.Selection([
        ('rotary', 'Rotary'),
        ('rotaract', 'Rotaract'),
        ('interact', 'Interact'),
        ('rota_kids', 'Rota-Kids'),
    ], string="Program Type")
    rotary_membership_id = fields.Char(string="Rotary Membership ID")
    rotary_club_id = fields.Many2one('res.partner', string="Rotary Club")
    program_type_id = fields.Many2one('program.type', string="Program Type Reference")


class ResUsers(models.Model):
    _inherit = "res.users"

    def _signup_create_user(self, values):
        """Ensure partner is updated with club/program data after signup"""
        user = super()._signup_create_user(values)
        partner = user.partner_id.sudo() if user else False

        if not partner:
            return user

        # Handle club type (custom field)
        club_type = values.get("club_type")
        if club_type:
            partner.write({"program_type": club_type})

        # Handle rotary_club_id (from form)
        rotary_club_id = values.get("rotary_club_id")
        if rotary_club_id:
            try:
                partner.write({"rotary_club_id": int(rotary_club_id)})
            except Exception:
                pass

        # Handle rotary_org_id or membership number
        rotary_org_id = values.get("rotary_org_id") or values.get("rotary_id")
        if rotary_org_id:
            partner.write({"rotary_membership_id": str(rotary_org_id)})

        return user
