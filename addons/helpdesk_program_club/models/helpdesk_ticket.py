# -*- coding: utf-8 -*-
from odoo import models, fields


class TicketHelpdesk(models.Model):
    _inherit = 'ticket.helpdesk'

    helpdesk_program_type = fields.Char(
        string='Program Type',
    )

    helpdesk_club_id = fields.Many2one(
        comodel_name='res.partner',
        string='Club Name',
    )
