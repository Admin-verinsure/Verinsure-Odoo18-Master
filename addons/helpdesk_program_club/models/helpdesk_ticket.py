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
        The website form posts helpdesk_club_id as a plain string (the partner
        id). Odoo's website-helpdesk base controller forwards ALL form kwargs
        into ticket.create() — so we cast the string to int here.

        Also guards against: "False", "0", "", 0 — all map to no value.
        """
        for vals in vals_list:
            self._sanitize_club_id(vals)
        return super().create(vals_list)

    def write(self, vals):
        """Same guard for backend edits."""
        self._sanitize_club_id(vals)
        return super().write(vals)

    @api.model
    def _sanitize_club_id(self, vals):
        """
        Cast helpdesk_club_id from string → int in-place.
        Removes the key entirely if the value is falsy or un-castable.
        """
        if 'helpdesk_club_id' not in vals:
            return
        raw = vals['helpdesk_club_id']
        if isinstance(raw, int):
            if raw == 0:
                vals['helpdesk_club_id'] = False
            return
        # It's a string (or something else from the HTTP form)
        if not raw or str(raw).strip() in ('False', 'false', '0', ''):
            vals['helpdesk_club_id'] = False
            return
        try:
            vals['helpdesk_club_id'] = int(raw)
        except (ValueError, TypeError):
            _logger.warning(
                "helpdesk_club_id: cannot cast %r to int — clearing field", raw
            )
            vals['helpdesk_club_id'] = False
