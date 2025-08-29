from odoo import models, fields

class ResPartner(models.Model):
    _inherit = "res.partner"

    club_type = fields.Selection([
        ('rotary', 'Rotary'),
        ('rotaract', 'Rotaract'),
        ('interact', 'Interact'),
        ('rotagkids', 'RotaKids'),
    ], string="Program Type")
