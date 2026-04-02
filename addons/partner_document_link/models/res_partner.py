# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    dms_file_count = fields.Integer(
        string='Documents',
        compute='_compute_dms_file_count',
    )

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _get_all_related_partner_ids(self):
        """
        For a company  → itself + all child contacts.
        For a contact  → only itself.
        This ensures that a company's button shows files tagged to
        any of its child contacts as well.
        """
        self.ensure_one()
        if self.is_company:
            children = self.env['res.partner'].search([
                ('parent_id', 'child_of', self.id),
            ])
            return (self | children).ids
        return self.ids

    # ------------------------------------------------------------------ #
    #  Computed field                                                      #
    # ------------------------------------------------------------------ #

    def _compute_dms_file_count(self):
        """
        Count DMS documents linked to this partner via the explicit
        partner_id field we add to dms.file AND via partner_id on
        dms.directory (all files inside a partner-linked folder count too).

        Two sources are combined without double-counting:
          1. Files where dms.file.partner_id = this partner
          2. Files inside directories where dms.directory.partner_id = this partner
        """
        DmsFile = self.env['dms.file']
        DmsDirectory = self.env['dms.directory']

        for partner in self:
            partner_ids = partner._get_all_related_partner_ids()

            # Source 1: files directly tagged to partner
            direct_file_ids = DmsFile.search([
                ('partner_id', 'in', partner_ids),
            ]).ids

            # Source 2: files inside directories tagged to partner
            linked_dir_ids = DmsDirectory.search([
                ('partner_id', 'in', partner_ids),
            ]).ids
            folder_file_ids = DmsFile.search([
                ('directory_id', 'in', linked_dir_ids),
            ]).ids if linked_dir_ids else []

            # Union (no duplicates)
            all_file_ids = list(set(direct_file_ids + folder_file_ids))
            partner.dms_file_count = len(all_file_ids)

    # ------------------------------------------------------------------ #
    #  Smart button action                                                 #
    # ------------------------------------------------------------------ #

    def action_open_dms_files(self):
        """
        Open ONLY the files associated with this partner — never the
        full DMS.

        Domain logic (strictly scoped):
          OR(
            dms.file.partner_id IN [partner + children],
            dms.file.directory_id IN [dirs where directory.partner_id IN ...]
          )

        Falls back to directory list if no files found yet, pre-filtered
        and pre-defaulted so new uploads auto-link to this partner.
        """
        self.ensure_one()
        partner_ids = self._get_all_related_partner_ids()

        # Collect directory IDs linked to this partner
        linked_dir_ids = self.env['dms.directory'].search([
            ('partner_id', 'in', partner_ids),
        ]).ids

        # Build OR domain — files either directly tagged OR inside tagged dirs
        file_domain = ['|',
            ('partner_id', 'in', partner_ids),
            ('directory_id', 'in', linked_dir_ids) if linked_dir_ids else (
                'id', '=', False   # always-false leaf when no dirs exist
            ),
        ]

        file_count = self.env['dms.file'].search_count(file_domain)

        if file_count:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Documents – %s' % self.name,
                'res_model': 'dms.file',
                'view_mode': 'list,form',
                'domain': file_domain,
                'context': {
                    # Pre-fill partner when user creates a new file from here
                    'default_partner_id': self.id,
                    'default_directory_id': linked_dir_ids[0] if linked_dir_ids else False,
                },
            }

        # No files yet — open directory list scoped to this partner
        # so user can create/upload into the right folder
        dir_domain = [('partner_id', 'in', partner_ids)]
        return {
            'type': 'ir.actions.act_window',
            'name': 'Document Folders – %s' % self.name,
            'res_model': 'dms.directory',
            'view_mode': 'list,form',
            'domain': dir_domain,
            'context': {
                'default_partner_id': self.id,
            },
        }
