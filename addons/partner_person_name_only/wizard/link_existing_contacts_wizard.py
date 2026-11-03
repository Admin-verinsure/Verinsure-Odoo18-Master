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

    mode = fields.Selection([
        ('link', 'Link contacts'),
        ('unlink', 'Unlink contacts'),
    ], default='link', required=True)

    def _partner_ids_domain(self):
        if self.mode == 'unlink':
            return [
                ('is_company', '=', False),
                ('parent_id', '=', self.company_id.id if self.company_id else False),
                ('id', '!=', self.company_id.id if self.company_id else False),
            ]
        return [
            ('is_company', '=', False),
            ('parent_id', '=', False),
            ('id', '!=', self.company_id.id if self.company_id else False),
        ]

    partner_ids = fields.Many2many(
        "res.partner",
        string="Contacts",
        domain=lambda self: self._partner_ids_domain(),
        help="Select existing individual contacts to link or unlink under this company. "
             "Unlinking clears the parent relationship without deleting the contact.",
    )

    def action_link(self):
        # Re-parent selected contacts under the company so they appear in Contacts & Addresses.
        self.ensure_one()
        if self.partner_ids:
            self.partner_ids.write({"parent_id": self.company_id.id})
        return {"type": "ir.actions.act_window_close"}

    def action_unlink(self):
        self.ensure_one()
        if self.partner_ids:
            self.partner_ids.filtered(lambda p: p.parent_id == self.company_id).write({"parent_id": False})
        return {"type": "ir.actions.act_window_close"}
