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

        Also guards against Odoo sending string "False" or "0" which would
        break the Many2one assignment.
        """
        for vals in vals_list:
            raw = vals.get('helpdesk_club_id')
            if raw is not None and not isinstance(raw, int):
                # "False", "", "0", None → remove the key entirely
                if raw in ('False', 'false', '', '0', 0, False):
                    vals.pop('helpdesk_club_id', None)
                else:
                    try:
                        vals['helpdesk_club_id'] = int(raw)
                    except (ValueError, TypeError):
                        _logger.warning(
                            "TicketHelpdesk.create: cannot cast helpdesk_club_id=%r to int — dropping",
                            raw,
                        )
                        vals.pop('helpdesk_club_id', None)
        return super().create(vals_list)
