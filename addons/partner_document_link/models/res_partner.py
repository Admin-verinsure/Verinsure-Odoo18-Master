# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dms_file_count = fields.Integer(
        string='Documents',
        compute='_compute_dms_file_count',
    )

    def _compute_dms_file_count(self):
        """
        Count dms.file records linked to this partner.

        OCA DMS links files to any record via res_model + res_id on
        dms.directory (the directory can be auto-created per record).
        We search dms.file by partner_id Many2one if it exists,
        OR fall back to res_model/res_id on dms.directory.

        Strategy used here (most compatible across DMS versions):
        - Search dms.file where the parent directory's res_model = 'res.partner'
          and res_id = partner.id
        - Also include child contacts for companies
        """
        DmsFile = self.env['dms.file']
        for partner in self:
            partner_ids = partner._get_all_related_partner_ids()
            count = DmsFile.search_count([
                ('res_model', '=', 'res.partner'),
                ('res_id', 'in', partner_ids),
            ])
            # Also count files in directories linked to the partner
            directory_count = self.env['dms.directory'].search_count([
                ('res_model', '=', 'res.partner'),
                ('res_id', 'in', partner_ids),
            ])
            # Use file count primarily; show directory count as fallback
            partner.dms_file_count = count if count else directory_count

    def _get_all_related_partner_ids(self):
        """
        For a company: return IDs of itself + all child contacts.
        For a contact: return only its own ID.
        """
        self.ensure_one()
        if self.is_company:
            children = self.env['res.partner'].search([
                ('parent_id', 'child_of', self.id),
            ])
            return (self | children).ids
        return self.ids

    def action_open_dms_files(self):
        """
        Open DMS file list filtered on this partner.
        Falls back to directory view if no direct file links found.
        """
        self.ensure_one()
        partner_ids = self._get_all_related_partner_ids()

        # Try to open dms.file records linked via res_model/res_id
        file_domain = [
            ('res_model', '=', 'res.partner'),
            ('res_id', 'in', partner_ids),
        ]
        file_count = self.env['dms.file'].search_count(file_domain)

        if file_count:
            return {
                'type': 'ir.actions.act_window',
                'name': '%s – Documents' % self.name,
                'res_model': 'dms.file',
                'view_mode': 'list,form',       # Odoo 18: 'list' not 'tree'
                'domain': file_domain,
                'context': {
                    'default_res_model': 'res.partner',
                    'default_res_id': self.id,
                },
            }

        # Fallback: open DMS directories linked to the partner
        dir_domain = [
            ('res_model', '=', 'res.partner'),
            ('res_id', 'in', partner_ids),
        ]
        return {
            'type': 'ir.actions.act_window',
            'name': '%s – Document Folders' % self.name,
            'res_model': 'dms.directory',
            'view_mode': 'list,form',
            'domain': dir_domain,
            'context': {
                'default_res_model': 'res.partner',
                'default_res_id': self.id,
            },
        }
