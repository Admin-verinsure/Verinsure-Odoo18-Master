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
        """Safety net: cast helpdesk_club_id string → int if it somehow arrives
        as a string (e.g. direct API calls, imports). The controller handles
        this for website submissions, but this guard covers all other paths."""
        for vals in vals_list:
            self._sanitize_club_id(vals)
        return super().create(vals_list)

    def write(self, vals):
        """Same guard for backend edits."""
        self._sanitize_club_id(vals)
        return super().write(vals)

    @api.model
    def _sanitize_club_id(self, vals):
        """Cast helpdesk_club_id from string → int in-place, or set False."""
        if 'helpdesk_club_id' not in vals:
            return
        raw = vals['helpdesk_club_id']
        if isinstance(raw, int):
            if raw == 0:
                vals['helpdesk_club_id'] = False
            return
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
