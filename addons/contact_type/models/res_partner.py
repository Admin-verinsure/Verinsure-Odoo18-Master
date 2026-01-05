# -*- coding: utf-8 -*-
# Part of YantrAdhigam Pvt Ltd. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    contact_type_ids = fields.Many2many(
        'partner.contact.type',
        'partner_contact_type_rel',
        'partner_id',
        'contact_type_id',
        string='Contact Types',
        help="Categories for this contact (Customer, Vendor, Distributor, etc.)"
    )
