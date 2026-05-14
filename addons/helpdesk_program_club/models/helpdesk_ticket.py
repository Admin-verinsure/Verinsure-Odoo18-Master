# -*- coding: utf-8 -*-
from odoo import models, fields


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    helpdesk_program_type = fields.Selection(
        related='partner_id.club_type',
        string='Program Type',
        store=True,
        readonly=False,
    )

    helpdesk_club_id = fields.Many2one(
        comodel_name='res.partner',
        string='Club Name',
        domain="[('club_type', '=', helpdesk_program_type), ('active', '=', True)]",
    )
