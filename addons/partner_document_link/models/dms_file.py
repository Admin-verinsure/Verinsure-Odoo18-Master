# -*- coding: utf-8 -*-
from odoo import models, fields


class DmsFile(models.Model):
    _inherit = 'dms.file'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Related Partner',
        index=True,
        tracking=True,
        help='Explicitly link this file to a Company or Contact.',
    )
