# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    document_count = fields.Integer(
        string='Documents',
        compute='_compute_document_count',
    )

    def _compute_document_count(self):
        """
        Count documents linked to this partner.
        documents.document uses 'partner_id' field in Odoo 18 Enterprise.
        We also include child contacts' documents when viewing a company.
        """
        Document = self.env['documents.document']
        for partner in self:
            # Gather the partner + all its child contacts (if company)
            partner_ids = partner._get_partner_ids_for_documents()
            partner.document_count = Document.search_count([
                ('partner_id', 'in', partner_ids),
                ('type', '!=', 'folder'),      # exclude folder entries
            ])

    def _get_partner_ids_for_documents(self):
        """
        Return the list of partner IDs to consider when counting/opening documents.
        For a company, include itself + all child contacts.
        For a contact, include only itself.
        """
        self.ensure_one()
        if self.is_company:
            # Include the company itself and all its child contacts
            children = self.env['res.partner'].search([
                ('parent_id', 'child_of', self.id),
            ])
            return (self | children).ids
        return self.ids

    def action_open_documents(self):
        """
        Action called by the smart button to open the Documents view
        filtered on this partner's documents.
        """
        self.ensure_one()
        partner_ids = self._get_partner_ids_for_documents()

        return {
            'type': 'ir.actions.act_window',
            'name': 'Documents',
            'res_model': 'documents.document',
            'view_mode': 'list,form,activity',      # Odoo 18: use 'list' not 'tree'
            'domain': [
                ('partner_id', 'in', partner_ids),
                ('type', '!=', 'folder'),
            ],
            'context': {
                'default_partner_id': self.id,      # pre-fill partner on new document
                'searchpanel_default_folder_id': False,
            },
        }
