# -*- coding: utf-8 -*-
from odoo import fields, models

class LinkExistingContactsWizard(models.TransientModel):
    _name = "link.existing.contacts.wizard"
    _description = "Link Existing Contacts to Company"

    company_id = fields.Many2one(
        "res.partner",
        string="Company",
        required=True,
        readonly=True,
    )

    partner_ids = fields.Many2many(
        "res.partner",
        string="Existing Contacts",
        domain="[('is_company','=',False), ('id','!=', company_id)]",
        help="Select existing individual contacts to link under this company. "
             "This will set their parent_id to the selected company.",
    )

    def action_link(self):
        # Re-parent selected contacts under the company so they appear in Contacts & Addresses.
        self.ensure_one()
        if self.partner_ids:
            self.partner_ids.write({"parent_id": self.company_id.id})
        return {"type": "ir.actions.act_window_close"}
