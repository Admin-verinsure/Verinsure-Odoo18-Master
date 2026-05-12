# -*- coding: utf-8 -*-
from odoo import models, fields


class HelpdeskTicket(models.Model):
    """
    Extend helpdesk.ticket with two custom fields:
      - program_type  : stores the club_type selection key (e.g. 'rotary', 'interact')
                        as a plain Char so it survives even if res.partner selection
                        changes later.
      - club_id       : Many2one to res.partner – the specific club the submitter
                        belongs to.

    Both fields are written by the website form controller override and are
    shown in the backend ticket form via helpdesk_ticket_fields.xml.
    """
    _inherit = 'helpdesk.ticket'

    program_type = fields.Char(
        string='Program Type',
        help='Program type selected by the submitter on the website form.',
    )

    club_id = fields.Many2one(
        comodel_name='res.partner',
        string='Club',
        ondelete='set null',
        help='Club selected by the submitter on the website form.',
    )

    # ── Email template helper ────────────────────────────────────────────────
    # The default website_helpdesk mail template uses ticket.description.
    # We surface program_type and club_id there automatically by appending
    # to description in the controller, so no template override is needed.
