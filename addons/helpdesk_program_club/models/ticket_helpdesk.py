# -*- coding: utf-8 -*-
from odoo import models, fields


class TicketHelpdesk(models.Model):
    _inherit = 'ticket.helpdesk'

    club_id = fields.Many2one(
        comodel_name='res.partner',
        string='Club',
        ondelete='set null',
    )
