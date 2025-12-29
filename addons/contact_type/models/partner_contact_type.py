# -*- coding: utf-8 -*-
# Part of YantrAdhigam Pvt Ltd. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class PartnerContactType(models.Model):
    _name = 'partner.contact.type'
    _description = 'Partner Contact Type'
    _order = 'sequence, name'
    _rec_name = 'name'

    contact_code = fields.Char(
        string='Code',
        readonly=True,
        copy=False,
        help="Unique code for this contact type"
    )
    name = fields.Char(
        string='Name',
        required=True,
        help="Name of the contact type (e.g., Customer, Vendor)"
    )
    description = fields.Text(
        string='Description',
        help="Detailed description of this contact type"
    )
    color = fields.Integer(
        string='Color',
        help="Color for kanban view"
    )
    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help="Used to order contact types"
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help="If unchecked, this contact type will be hidden"
    )
    partner_ids = fields.Many2many(
        'res.partner',
        'partner_contact_type_rel',
        'contact_type_id',
        'partner_id',
        string='Partners',
        help="Partners with this contact type"
    )
    partner_count = fields.Integer(
        string='Partners Count',
        compute='_compute_partner_count',
        help="Number of partners with this contact type"
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Contact type name must be unique!'),
        ('contact_code_uniq', 'unique(contact_code)', 'Contact code must be unique!'),
    ]

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for record in self:
            record.partner_count = len(record.partner_ids)

    @api.model
    def create(self, vals):
        if vals.get('contact_code', 'New') == 'New':
            vals['contact_code'] = self.env['ir.sequence'].next_by_code('partner.contact.type') or 'New'
        return super(PartnerContactType, self).create(vals)

    def action_view_partners(self):
        """Action to view partners with this contact type"""
        self.ensure_one()
        return {
            'name': _('Partners - %s') % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'domain': [('contact_type_ids', 'in', self.id)],
            'context': {'default_contact_type_ids': [(6, 0, [self.id])]},
            'views': [(False, 'list'), (False, 'form')],
            'view_mode': 'list,form',
        }

