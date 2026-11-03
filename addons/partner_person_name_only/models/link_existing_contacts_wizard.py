# -*- coding: utf-8 -*-
from odoo import fields, models


class LinkExistingContactsWizard(models.TransientModel):
    _name = "link.existing.contacts.wizard"
    _description = "Link Existing Contacts to a Parent Contact"

    # We keep the field name company_id for backward-compat with the action/context,
    # but it can point to either a company or an individual (any res.partner record).
    company_id = fields.Many2one("res.partner", required=True, string="Parent Contact")
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

    # Only allow linking contacts that currently have NO parent, or unlinking only
    # contacts currently linked to the selected parent contact.
    partner_ids = fields.Many2many(
        "res.partner",
        string="Contacts",
        domain=lambda self: self._partner_ids_domain(),
        help="Select contacts to link or unlink under the Parent Contact. "
             "Unlinking clears the parent relationship without deleting the contact."
    )

    def action_link(self):
        self.ensure_one()
        # Set the parent_id of selected contacts so they appear under Contacts & Addresses
        self.partner_ids.write({'parent_id': self.company_id.id})
        return {'type': 'ir.actions.act_window_close'}

    def action_unlink(self):
        self.ensure_one()
        # Safest unlink: only clear parent_id for contacts currently attached to this parent.
        # This removes the relationship without deleting the contact record itself.
        self.partner_ids.filtered(lambda p: p.parent_id == self.company_id).write({'parent_id': False})
        return {'type': 'ir.actions.act_window_close'}
