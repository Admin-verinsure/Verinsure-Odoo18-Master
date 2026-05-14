# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class TicketHelpdesk(models.Model):
    _inherit = 'ticket.helpdesk'

    helpdesk_club_id = fields.Many2one(
        comodel_name='res.partner',
        string='Club Name',
    )

    @api.model_create_multi
    def create(self, vals_list):
        """
        The website form submits helpdesk_club_id as a plain integer string
        (the partner id). Odoo's website controller passes unknown fields
        through as strings in the vals dict — we cast it here before the
        record is written so it lands correctly as a Many2one id.
        """
        for vals in vals_list:
            raw = vals.get('helpdesk_club_id')
            if raw and not isinstance(raw, int):
                try:
                    vals['helpdesk_club_id'] = int(raw)
                except (ValueError, TypeError):
                    vals.pop('helpdesk_club_id', None)
        return super().create(vals_list)
