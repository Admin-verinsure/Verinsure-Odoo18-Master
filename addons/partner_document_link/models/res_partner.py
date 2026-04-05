# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dms_file_count = fields.Integer(
        string='Documents',
        compute='_compute_dms_file_count',
    )

    def _get_all_related_partner_ids(self):
        """Company → itself + all child contacts. Contact → itself only."""
        self.ensure_one()
        if self.is_company:
            children = self.env['res.partner'].search([
                ('parent_id', 'child_of', self.id),
            ])
            return (self | children).ids
        return self.ids

    def _compute_dms_file_count(self):
        """
        Count dms.file records linked to this partner via:
          1. dms.file.partner_id  (direct file tag)
          2. dms.directory.partner_id → files in those directories
        Both sources are unioned (no double-count).
        """
        DmsFile = self.env['dms.file']
        DmsDirectory = self.env['dms.directory']

        for partner in self:
            pids = partner._get_all_related_partner_ids()

            direct_ids = set(DmsFile.search([
                ('partner_id', 'in', pids),
            ]).ids)

            dir_ids = DmsDirectory.search([
                ('partner_id', 'in', pids),
            ]).ids
            folder_ids = set(DmsFile.search([
                ('directory_id', 'in', dir_ids),
            ]).ids) if dir_ids else set()

            partner.dms_file_count = len(direct_ids | folder_ids)

    def action_open_dms_files(self):
        """
        Open ONLY files belonging to this partner.
        Falls back to directory view if no files exist yet.
        """
        self.ensure_one()
        pids = self._get_all_related_partner_ids()

        dir_ids = self.env['dms.directory'].search([
            ('partner_id', 'in', pids),
        ]).ids

        # OR domain: files tagged directly OR inside a tagged directory
        if dir_ids:
            file_domain = [
                '|',
                ('partner_id', 'in', pids),
                ('directory_id', 'in', dir_ids),
            ]
        else:
            file_domain = [('partner_id', 'in', pids)]

        file_count = self.env['dms.file'].search_count(file_domain)

        if file_count:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Documents – %s' % self.name,
                'res_model': 'dms.file',
                'view_mode': 'list,form',
                'domain': file_domain,
                'context': {
                    'default_partner_id': self.id,
                    'default_directory_id': dir_ids[0] if dir_ids else False,
                },
            }

        # No files yet — show (empty) directory list for this partner
        return {
            'type': 'ir.actions.act_window',
            'name': 'Document Folders – %s' % self.name,
            'res_model': 'dms.directory',
            'view_mode': 'list,form',
            'domain': [('partner_id', 'in', pids)],
            'context': {'default_partner_id': self.id},
        }
