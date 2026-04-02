# -*- coding: utf-8 -*-
from odoo import models, fields


class DmsFile(models.Model):
    _inherit = 'dms.file'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Related Partner',
        index=True,
        tracking=True,
        help='Link this document directly to a company or contact. '
             'Once set, the document will appear on that partner\'s '
             'Documents smart button.',
    )
