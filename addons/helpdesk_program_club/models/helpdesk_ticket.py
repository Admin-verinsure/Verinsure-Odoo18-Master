# -*- coding: utf-8 -*-
from odoo import models, fields


class HelpdeskTicket(models.Model):
    _inherit = 'ticket.helpdesk'

    program_type = fields.Char(
        string='Program Type',
        help='Program type selected on the website form.',
    )
    club_id = fields.Many2one(
        comodel_name='res.partner',
        string='Club',
        ondelete='set null',
        help='Club selected on the website form.',
    )
