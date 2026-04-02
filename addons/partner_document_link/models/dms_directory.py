# -*- coding: utf-8 -*-
from odoo import models, fields


class DmsDirectory(models.Model):
    _inherit = 'dms.directory'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Related Partner',
        index=True,
        tracking=True,
        help='Link this folder directly to a company or contact. '
             'All files inside this folder will also count toward '
             'that partner\'s Documents smart button.',
    )
