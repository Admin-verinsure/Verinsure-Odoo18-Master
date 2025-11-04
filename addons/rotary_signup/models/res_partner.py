# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = "res.partner"

    # Flag to identify Rotary clubs
    is_rotary_club = fields.Boolean(string="Is Rotary Club", default=False)

    # Human-readable club name
    club_name = fields.Char(string="Club Name")

    # Static or selection-based program type for clubs (used in filters)
    program_type = fields.Selection([
        ('rotary', 'Rotary'),
        ('rotaract', 'Rotaract'),
        ('interact', 'Interact'),
        ('rota_kids', 'Rota-Kids'),
    ], string="Program Type")

    # For storing Rotary membership ID (user/member unique number)
    rotary_membership_id = fields.Char(string="Rotary Membership ID")

    # Link to the parent Rotary Club partner
    rotary_club_id = fields.Many2one(
        'res.partner',
        string="Rotary Club",
        domain=[('is_rotary_club', '=', True)],
        help="Select the Rotary Club this user belongs to."
    )

    # Optional dynamic program type reference (if program.type model exists)
    program_type_id = fields.Many2one(
        'program.type',
        string="Program Type Reference",
        help="Reference to Program Type record if dynamically managed."
    )


class ResUsers(models.Model):
    _inherit = "res.users"

    def _signup_create_user(self, values):
        """Ensure partner gets Rotary-related fields after signup"""
        user = super()._signup_create_user(values)
        partner = user.partner_id.sudo() if user else False

        if not partner:
            return user

        # --- 1️⃣ Program Type (string or selection)
        program_type = values.get("club_type") or values.get("program_type")
        if program_type:
            partner.write({"program_type": program_type})

        # --- 2️⃣ Rotary Club Link
        rotary_club_id = values.get("rotary_club_id")
        if rotary_club_id:
            try:
                partner.write({"rotary_club_id": int(rotary_club_id)})
            except Exception:
                pass

        # --- 3️⃣ Rotary Membership or Org ID
        rotary_org_id = values.get("rotary_org_id") or values.get("rotary_id")
        if rotary_org_id:
            partner.write({"rotary_membership_id": str(rotary_org_id)})

        return user
