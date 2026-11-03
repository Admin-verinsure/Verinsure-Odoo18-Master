# -*- coding: utf-8 -*-
from odoo import fields, models

class LinkExistingContactsWizard(models.TransientModel):
    _name = "link.existing.contacts.wizard"
    _description = "Link Existing Contacts to a Parent Contact"

    # We keep the field name company_id for backward-compat with the action/context,
    # but it can point to either a company or an individual (any res.partner record).
    company_id = fields.Many2one("res.partner", required=True, string="Parent Contact")

    # Option B (safer): only allow linking contacts that currently have NO parent.
    # Also restrict to persons (not companies) and exclude the parent contact itself.
    partner_ids = fields.Many2many(
        "res.partner",
        string="Existing Contacts",
        domain="[('is_company','=',False), ('parent_id','=',False), ('id','!=', company_id)]",
        help="Select existing individual contacts (unlinked) to attach under the Parent Contact."
    )

    def action_link(self):
        self.ensure_one()
        # Set the parent_id of selected contacts so they appear under Contacts & Addresses
        self.partner_ids.write({'parent_id': self.company_id.id})
        return {'type': 'ir.actions.act_window_close'}
