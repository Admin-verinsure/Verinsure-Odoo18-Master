# -*- coding: utf-8 -*-
from odoo import models, fields


class DmsDirectory(models.Model):
    _inherit = 'dms.directory'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Related Partner',
        index=True,
        tracking=True,
        help='Explicitly link this folder to a Company or Contact. '
             'Files inside it will also count on that partner\'s smart button.',
    )
