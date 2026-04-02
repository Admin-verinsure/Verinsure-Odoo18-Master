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
        """
        self.ensure_one()
        if self.is_company:
            children = self.env['res.partner'].search([
                ('parent_id', 'child_of', self.id),
            ])
            return (self | children).ids
        return self.ids

    def _get_partner_directory_ids(self, partner_ids):
        """
        Return ALL dms.directory IDs that are directly linked to any of
        the given partner IDs via res_model / res_id on the directory.

        In OCA DMS the directory stores res_model + res_id.
        Files inherit those fields as related fields through their
        directory_id → directory.res_model / directory.res_id.
        """
        return self.env['dms.directory'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', 'in', partner_ids),
        ]).ids

    def _get_all_subdirectory_ids(self, root_dir_ids):
        """
        Recursively collect a directory and ALL its child directories.
        DMS uses parent_id to build the folder tree; files can be stored
        in any sub-level, so we need every descendant directory ID to
        build a correct domain for dms.file.
        """
        if not root_dir_ids:
            return []
        all_ids = list(root_dir_ids)
        children = self.env['dms.directory'].search([
            ('parent_id', 'in', root_dir_ids),
        ]).ids
        if children:
            all_ids += self._get_all_subdirectory_ids(children)
        return all_ids

    # ------------------------------------------------------------------ #
    #  Computed field                                                      #
    # ------------------------------------------------------------------ #

    def _compute_dms_file_count(self):
        """
        Count only the files (dms.file) that belong to directories
        directly linked to this partner (and its child contacts).

        Counting strategy:
          1. Find root directories where res_model='res.partner'
             and res_id ∈ partner_ids
          2. Walk all sub-directories recursively
          3. Count dms.file records inside those directories

        This guarantees we NEVER show files from other partners.
        """
        DmsFile = self.env['dms.file']
        DmsDirectory = self.env['dms.directory']

        for partner in self:
            partner_ids = partner._get_all_related_partner_ids()

            # Root dirs linked directly to this partner
            root_dir_ids = DmsDirectory.search([
                ('res_model', '=', 'res.partner'),
                ('res_id', 'in', partner_ids),
            ]).ids

            if not root_dir_ids:
                partner.dms_file_count = 0
                continue

            # All dirs including nested children
            all_dir_ids = partner._get_all_subdirectory_ids(root_dir_ids)

            partner.dms_file_count = DmsFile.search_count([
                ('directory_id', 'in', all_dir_ids),
            ])

    # ------------------------------------------------------------------ #
    #  Button action                                                       #
    # ------------------------------------------------------------------ #

    def action_open_dms_files(self):
        """
        Smart button action: open ONLY the files/directories that belong
        to this partner — never the entire DMS.

        Logic:
        - If partner has linked directories → show dms.file list
          filtered strictly to those directory trees.
        - If directories exist but are empty → open the directory list
          so the user can upload into the correct folder.
        - If nothing exists yet → open the directory list pre-filtered
          and pre-defaulted to create a new folder for this partner.
        """
        self.ensure_one()
        partner_ids = self._get_all_related_partner_ids()

        # Step 1: find root directories for this partner
        root_dirs = self.env['dms.directory'].search([
            ('res_model', '=', 'res.partner'),
            ('res_id', 'in', partner_ids),
        ])

        if root_dirs:
            # Expand to all nested sub-directories
            all_dir_ids = self._get_all_subdirectory_ids(root_dirs.ids)

            # Check if there are any files inside those dirs
            file_domain = [('directory_id', 'in', all_dir_ids)]
            file_count = self.env['dms.file'].search_count(file_domain)

            if file_count:
                # ── Show file list filtered to this partner only ──────── #
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Documents – %s' % self.name,
                    'res_model': 'dms.file',
                    'view_mode': 'list,form',          # v18: list not tree
                    'domain': file_domain,             # STRICT partner filter
                    'context': {
                        # Pre-fill directory when user creates a new file
                        'default_directory_id': root_dirs[0].id,
                    },
                }
            else:
                # Dirs exist but are empty → open directory so user can upload
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Document Folders – %s' % self.name,
                    'res_model': 'dms.directory',
                    'view_mode': 'list,form',
                    'domain': [('id', 'in', root_dirs.ids)],   # only partner dirs
                    'context': {
                        'default_res_model': 'res.partner',
                        'default_res_id': self.id,
                    },
                }

        # Step 2: no directory yet → open directory list pre-configured
        # for this partner so the user can create the first folder
        return {
            'type': 'ir.actions.act_window',
            'name': 'Document Folders – %s' % self.name,
            'res_model': 'dms.directory',
            'view_mode': 'list,form',
            'domain': [
                ('res_model', '=', 'res.partner'),
                ('res_id', 'in', partner_ids),
            ],
            'context': {
                # Pre-fill fields so new directory auto-links to partner
                'default_res_model': 'res.partner',
                'default_res_id': self.id,
            },
        }
